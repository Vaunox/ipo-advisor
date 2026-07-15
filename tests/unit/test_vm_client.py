"""App-side VM client (v3 V3-1 step 2) — fail-loud fetch + validation.

The client must NOT trust a 200: a malformed/truncated body, a non-200, or a connection error all
raise :class:`VmUnavailable` so the caller falls back to local rather than feeding garbage in.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest
import requests

from ipo.core.types import IPORecord, Segment
from ipo.vm.client import VmClient, VmUnavailable


def _record_dict() -> dict[str, Any]:
    rec = IPORecord(
        ipo_id="acme",
        name="Acme Ltd",
        segment=Segment("mainboard"),
        price_band_low=100.0,
        price_band_high=110.0,
        open_date=date(2026, 7, 1),
        close_date=date(2026, 7, 3),
        qib_sub=3.0,
        captured_at=datetime(2026, 7, 3, 17, 0),
    )
    return rec.model_dump(mode="json")


class _FakeResp:
    def __init__(self, status_code: int, payload: object = None, *, bad_json: bool = False) -> None:
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self) -> object:
        if self._bad_json:
            raise ValueError("truncated body")
        return self._payload


def _patch(monkeypatch: pytest.MonkeyPatch, fn: object) -> None:
    monkeypatch.setattr("ipo.vm.client.requests.get", fn)


def test_valid_records_are_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"refreshed_at": "2026-07-14T09:00:00+05:30", "records": [_record_dict()]}
    _patch(monkeypatch, lambda url, timeout: _FakeResp(200, payload))
    env = VmClient("http://vm").fetch_records()
    assert [r.ipo_id for r in env.records] == ["acme"]
    assert env.refreshed_at is not None


def test_malformed_200_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # A 200 whose body is the wrong shape must NOT be trusted — it falls back, not feeds garbage.
    bad = {"refreshed_at": None, "records": [{"not": "a record"}]}
    _patch(monkeypatch, lambda url, timeout: _FakeResp(200, bad))
    with pytest.raises(VmUnavailable):
        VmClient("http://vm", retries=0).fetch_records()


def test_truncated_body_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, lambda url, timeout: _FakeResp(200, bad_json=True))
    with pytest.raises(VmUnavailable):
        VmClient("http://vm", retries=0).fetch_records()


def test_non_200_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, lambda url, timeout: _FakeResp(503))
    with pytest.raises(VmUnavailable):
        VmClient("http://vm", retries=0).fetch_context()


def test_connection_error_is_unavailable_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def boom(url: str, timeout: float) -> _FakeResp:
        calls["n"] += 1
        raise requests.ConnectionError("connection refused")

    _patch(monkeypatch, boom)
    with pytest.raises(VmUnavailable):
        VmClient("http://vm", retries=2).fetch_records()
    assert calls["n"] == 3  # 1 attempt + 2 retries, then give up


def test_context_envelope_is_validated_loosely(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"refreshed_at": "2026-07-14T09:00:00+05:30", "ipos": {"ACME": {"isin": "INE0X"}}}
    _patch(monkeypatch, lambda url, timeout: _FakeResp(200, payload))
    env = VmClient("http://vm").fetch_context()
    assert env.ipos["ACME"]["isin"] == "INE0X"
