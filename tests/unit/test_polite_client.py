"""Polite-scraper primitives: immutable cache, robots gate, retry/backoff, caching."""

from __future__ import annotations

import logging
import os
import urllib.robotparser
from datetime import datetime
from pathlib import Path

import pytest
import requests

from ipo.core.constants import IST
from ipo.core.types import RawResponse
from ipo.data.sources.base import (
    PoliteClient,
    RawCache,
    SourceError,
    compute_hash,
)


class _FakeResponse:
    def __init__(self, text: str, url: str = "https://example.test/x") -> None:
        self.text = text
        self.url = url

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    """Session whose .get replays a queued list of texts or exceptions to raise."""

    def __init__(self, behaviors: list[object]) -> None:
        self._behaviors = behaviors
        self.calls = 0

    def get(self, url: str, params=None, headers=None, timeout=None):  # type: ignore[no-untyped-def]
        behavior = self._behaviors[self.calls]
        self.calls += 1
        if isinstance(behavior, Exception):
            raise behavior
        return _FakeResponse(str(behavior), url=url)


def _client(session: _FakeSession, **kw: object) -> PoliteClient:
    return PoliteClient(
        user_agent="ipo-advisor-test",
        rate_limit_per_sec=0,  # no throttle in tests
        respect_robots=False,
        session=session,  # type: ignore[arg-type]
        sleep=lambda _s: None,  # no real waiting
        **kw,  # type: ignore[arg-type]
    )


def test_raw_cache_roundtrip_and_immutable(tmp_path: Path) -> None:
    cache = RawCache(root=tmp_path)
    resp = RawResponse(
        source="src",
        url="https://example.test/a",
        fetched_at=datetime(2026, 1, 1, tzinfo=IST),
        content="hello",
        content_hash=compute_hash("hello"),
    )
    assert cache.get("src", "https://example.test/a") is None
    cache.store(resp, request_id="https://example.test/a")
    loaded = cache.get("src", "https://example.test/a")
    assert loaded is not None and loaded.content == "hello"

    # Immutable: a second store under the same key does not overwrite.
    changed = resp.model_copy(update={"content": "tampered"})
    cache.store(changed, request_id="https://example.test/a")
    again = cache.get("src", "https://example.test/a")
    assert again is not None and again.content == "hello"


def test_fetch_success_hashes_content() -> None:
    session = _FakeSession(["<html>ok</html>"])
    client = _client(session)
    resp = client.fetch("src", "https://example.test/x")
    assert resp.content == "<html>ok</html>"
    assert resp.content_hash == compute_hash("<html>ok</html>")
    assert session.calls == 1


def test_fetch_retries_then_raises() -> None:
    session = _FakeSession([requests.ConnectionError("boom")] * 3)
    client = _client(session, max_retries=3)
    with pytest.raises(SourceError):
        client.fetch("src", "https://example.test/x")
    assert session.calls == 3


def test_fetch_recovers_after_transient_error() -> None:
    session = _FakeSession([requests.ConnectionError("boom"), "recovered"])
    client = _client(session, max_retries=3)
    resp = client.fetch("src", "https://example.test/x")
    assert resp.content == "recovered"
    assert session.calls == 2


def test_robots_disallow_blocks_fetch() -> None:
    session = _FakeSession(["should not be reached"])
    client = PoliteClient(
        user_agent="ipo-advisor-test",
        rate_limit_per_sec=0,
        respect_robots=True,
        session=session,  # type: ignore[arg-type]
        sleep=lambda _s: None,
    )
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(["User-agent: *", "Disallow: /"])
    client._robots["https://example.test"] = parser  # preload to avoid network
    with pytest.raises(SourceError):
        client.fetch("src", "https://example.test/blocked")
    assert session.calls == 0


def test_get_or_fetch_uses_cache_on_second_call(tmp_path: Path) -> None:
    session = _FakeSession(["first"])  # only one network response available
    client = _client(session)
    cache = RawCache(root=tmp_path)
    a = client.get_or_fetch(cache, "src", "https://example.test/x")
    b = client.get_or_fetch(cache, "src", "https://example.test/x")
    assert a.content == b.content == "first"
    assert session.calls == 1  # second call served from cache


# --- Durability (code review #7: atomic write + poisoned-read SourceError wrap) ----------------


def _entry(cache: RawCache, url: str = "https://example.test/x") -> RawResponse:
    resp = RawResponse(
        source="src",
        url=url,
        fetched_at=datetime(2026, 1, 1, tzinfo=IST),
        content="orig",
        content_hash=compute_hash("orig"),
    )
    cache.store(resp, request_id=url)
    return resp


def test_store_is_atomic_and_leaves_no_tmp(tmp_path: Path) -> None:
    cache = RawCache(root=tmp_path)
    _entry(cache)
    assert list(tmp_path.glob("**/*.tmp")) == []  # os.replace cleaned up the atomic write
    got = cache.get("src", "https://example.test/x")
    assert got is not None and got.content == "orig"  # round-trips


def test_poisoned_entry_raises_sourceerror_and_quarantines(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cache = RawCache(root=tmp_path)
    _entry(cache)
    entry = next(tmp_path.glob("**/*.json"))
    poison = os.urandom(64)
    entry.write_bytes(poison)  # torn/garbage -> UnicodeDecodeError at the utf-8 decode

    with caplog.at_level(logging.WARNING):
        with pytest.raises(SourceError):  # NOT a raw ValueError-family escapee (the #7 fix)
            cache.get("src", "https://example.test/x")

    quarantine = entry.with_suffix(entry.suffix + ".corrupt")
    assert quarantine.read_bytes() == poison  # poisoned bytes preserved for inspection
    assert not entry.is_file()  # moved aside so the write-once store can heal
    assert [r for r in caplog.records if r.getMessage() == "raw_cache_entry_corrupt"]


def test_poisoned_entry_self_heals_on_next_fetch(tmp_path: Path) -> None:
    cache = RawCache(root=tmp_path)
    url = "https://example.test/x"
    _entry(cache)
    entry = next(tmp_path.glob("**/*.json"))
    entry.write_bytes(b"\xff\xfe torn")

    with pytest.raises(SourceError):  # a read now degrades + quarantines the poison
        cache.get("src", url)
    assert entry.with_suffix(entry.suffix + ".corrupt").is_file()

    # Self-heal: the poison is gone from the live path, so the next fetch re-populates it.
    client = _client(_FakeSession(["fresh"]))
    got = client.get_or_fetch(cache, "src", url)
    assert got.content == "fresh"  # re-fetched and re-cached
    reread = cache.get("src", url)
    assert reread is not None and reread.content == "fresh"  # reads clean now
