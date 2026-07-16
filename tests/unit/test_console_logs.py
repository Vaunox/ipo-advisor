"""Debug-console log pipeline (v3 V3-16): the ring buffer, the file reader, and expiry.

The headline guarantee: **both** paths the console reads — the in-memory ring buffer (live tail)
and the rotated files (history) — are redacted at write time, so a token/PAN/auth-header can never
reach the console. Plus: monotonic seq + ``since`` polling, bounded capacity (FIFO eviction),
newest-limit file history that skips torn lines, and time-expiry on top of the size cap.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from ipo.core.logging import RingBufferHandler, _expire_old_logs, redacted_payload
from ipo.service import logs as logs_mod
from ipo.service.logs import clamp_limit, file_history, ring_tail


def _record(msg: str, level: str = "INFO", **extra: object) -> logging.LogRecord:
    rec = logging.LogRecord("ipo.test", getattr(logging, level), __file__, 1, msg, None, None)
    for key, value in extra.items():
        setattr(rec, key, value)
    return rec


def test_ring_captures_message_extras_and_monotonic_seq() -> None:
    ring = RingBufferHandler(capacity=100)
    ring.emit(_record("scheduler_cycle_start"))
    ring.emit(_record("verdict_transition", ipo_id="smartworks", probability=0.71))

    entries = ring.entries()
    assert [e["message"] for e in entries] == ["scheduler_cycle_start", "verdict_transition"]
    assert entries[0]["seq"] == 1 and entries[1]["seq"] == 2
    assert entries[1]["ipo_id"] == "smartworks" and entries[1]["probability"] == 0.71
    assert entries[0]["level"] == "INFO"
    assert ring.latest_seq() == 2


def test_ring_since_returns_only_newer() -> None:
    ring = RingBufferHandler()
    ring.emit(_record("a"))
    ring.emit(_record("b"))
    ring.emit(_record("c"))
    assert [e["message"] for e in ring.entries(since=2)] == ["c"]
    assert ring.entries(since=3) == []  # nothing newer than the latest seq


def test_ring_evicts_oldest_past_capacity() -> None:
    ring = RingBufferHandler(capacity=3)
    for i in range(5):
        ring.emit(_record(f"e{i}"))
    entries = ring.entries()
    assert [e["message"] for e in entries] == ["e2", "e3", "e4"]  # oldest two evicted
    assert entries[-1]["seq"] == 5  # seq keeps counting past eviction (poll cursor stays correct)


def test_ring_redacts_secrets_at_store_time() -> None:
    # The console reads this buffer — a secret must be scrubbed on the way IN, not trusted to a
    # caller. Secret-keyed value dropped; a Bearer smuggled under an innocuous key pattern-scrubbed.
    ring = RingBufferHandler()
    ring.emit(
        _record("upstox_call", token="super-secret-value", detail="Bearer abcdefghijklmnop123")
    )
    entry = ring.entries()[0]
    assert entry["token"] == "[REDACTED]"  # secret key
    assert "abcdefghijklmnop123" not in json.dumps(entry)  # bearer-shaped value scrubbed

    payload = redacted_payload(_record("login", pan="ABCDE1234F"))
    assert payload["pan"] == "[REDACTED]"  # PAN key redacted on the console path too


def test_ring_emit_never_raises_on_a_bad_record() -> None:
    ring = RingBufferHandler()
    ring.handleError = lambda record: None  # type: ignore[method-assign]  # swallow the reported error
    bad = _record("x")
    bad.args = ("unclosed %s",)  # getMessage() will raise on formatting → emit must not propagate
    ring.emit(bad)  # must not raise
    assert ring.entries() == []  # nothing stored, but the caller was never broken


def test_file_history_parses_and_skips_torn_lines(tmp_path: Path) -> None:
    (tmp_path / "engine.log").write_text(
        '{"message":"a","level":"INFO"}\n'
        "not-json-a-torn-line\n"
        '{"message":"b","level":"WARN"}\n',
        encoding="utf-8",
    )
    out = file_history(tmp_path, limit=10)
    assert [e["message"] for e in out] == ["a", "b"]  # bad line skipped, not fatal


def test_file_history_newest_limit_across_rotations(tmp_path: Path) -> None:
    (tmp_path / "engine.log.1").write_text(
        '{"message":"old1"}\n{"message":"old2"}\n', encoding="utf-8"
    )
    (tmp_path / "engine.log").write_text(
        '{"message":"new1"}\n{"message":"new2"}\n', encoding="utf-8"
    )
    out = file_history(tmp_path, limit=3)
    assert [e["message"] for e in out] == ["old2", "new1", "new2"]  # newest 3, chronological


def test_file_history_empty_when_no_files(tmp_path: Path) -> None:
    assert file_history(tmp_path, limit=10) == []


def test_file_history_before_paginates_older_inclusive(tmp_path: Path) -> None:
    # v3 V3-16 unified stream: scroll-back pages older disk chunks via a `before` ts cursor.
    (tmp_path / "engine.log").write_text(
        '{"ts":"2026-07-16T09:00:00+05:30","message":"a"}\n'
        '{"ts":"2026-07-16T10:00:00+05:30","message":"b"}\n'
        '{"ts":"2026-07-16T11:00:00+05:30","message":"c"}\n',
        encoding="utf-8",
    )
    # before=10:00 → only entries with ts <= 10:00 (inclusive boundary, so the seam has no gap)
    out = file_history(tmp_path, limit=10, before="2026-07-16T10:00:00+05:30")
    assert [e["message"] for e in out] == ["a", "b"]
    # a tighter limit returns the NEWEST of that older set (chronological order preserved)
    out2 = file_history(tmp_path, limit=1, before="2026-07-16T10:00:00+05:30")
    assert [e["message"] for e in out2] == ["b"]
    # no cursor → the newest `limit` overall
    assert [e["message"] for e in file_history(tmp_path, limit=2)] == ["b", "c"]


def test_expire_deletes_stale_rotations_keeps_fresh_and_live(tmp_path: Path) -> None:
    stale = tmp_path / "engine.log.4"
    stale.write_text("x", encoding="utf-8")
    fresh = tmp_path / "engine.log.1"
    fresh.write_text("y", encoding="utf-8")
    live = tmp_path / "engine.log"
    live.write_text("live", encoding="utf-8")
    old = time.time() - 20 * 86_400
    os.utime(stale, (old, old))

    _expire_old_logs(tmp_path, max_age_days=14)

    assert not stale.exists()  # older than 14d → gone
    assert fresh.exists()  # recent rotation kept
    assert live.exists()  # the live file isn't matched by engine.log.* → never touched


def test_ring_tail_empty_when_ring_unconfigured(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(logs_mod, "get_ring_buffer", lambda: None)
    assert ring_tail(since=0, limit=10) == ([], 0)  # degrades to empty, never errors


def test_ring_tail_serves_since_and_cursor(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ring = RingBufferHandler()
    ring.emit(_record("a"))
    ring.emit(_record("b"))
    monkeypatch.setattr(logs_mod, "get_ring_buffer", lambda: ring)
    entries, last_seq = ring_tail(since=1, limit=10)
    assert [e["message"] for e in entries] == ["b"] and last_seq == 2


def test_clamp_limit_bounds() -> None:
    assert clamp_limit(0) == 500 and clamp_limit(-5) == 500  # non-positive → default
    assert clamp_limit(10) == 10
    assert clamp_limit(10_000_000) == 5000  # capped
