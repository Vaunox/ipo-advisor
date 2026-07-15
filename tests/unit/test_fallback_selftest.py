"""Weekly fallback self-test (v3 V3-4) — drives the REAL local path; only the trigger is faked.

The headline proof (operator's ask): the self-test PASSES on a working local scrape (valid records)
and FAILS on a rotted one (a feed-shape break → SourceError → ok=False), surfacing as
``[STALE] local fallback - self-test FAILED``. Only the NSE *source* is canned —
``refresh_data_plane`` → its ``except VmUnavailable`` branch → ``refresh_from_nse`` →
``build_live_records`` → the record write is all genuine. Plus: the scratch store is always cleaned
staleness-of-the-test-itself is caught. Offline + deterministic.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ipo.data.sources.base import SourceError
from ipo.data.sources.nse import NseClient, NseCurrentIssue, NseSubscription
from ipo.service.fallback_selftest import (
    SelftestResult,
    check_selftest,
    read_selftest,
    run_fallback_selftest,
    write_selftest,
)
from ipo.service.heartbeat import OK, STALE, UNKNOWN

_IST = timezone(timedelta(hours=5, minutes=30))
_NOW = datetime(2026, 7, 15, 12, 0, tzinfo=_IST)

_ISSUE = NseCurrentIssue(
    symbol="TESTCO",
    company="Test Co Ltd",
    segment="mainboard",
    price_band_low=100.0,
    price_band_high=110.0,
    open_date=date(2026, 7, 1),
    close_date=date(2026, 7, 3),
)
_SUB = NseSubscription(qib=5.0, nii=3.0, retail=2.0, total=4.0)


class _CannedNse(NseClient):
    """A canned NSE source (no network) — fakes ONLY the upstream data, never the fallback path.

    ``fail`` selects the rot case: ``current_issues`` raising ``SourceError`` is exactly what a
    changed/unreachable NSE feed does, and it must flip the self-test to FAILED.
    """

    def __init__(self, *, fail: bool = False, boom: Exception | None = None) -> None:
        self._fail = fail
        self._boom = boom

    def current_issues(self, *, force: bool = True) -> list[NseCurrentIssue]:
        if self._boom is not None:
            raise self._boom
        if self._fail:
            raise SourceError("canned: NSE current-issues feed shape changed")
        return [_ISSUE]

    def upcoming_issues(self, *, force: bool = True) -> list[NseCurrentIssue]:
        return []

    def subscription(self, symbol: str, *, force: bool = False) -> NseSubscription:
        return _SUB

    def past_issues(self, *, force: bool = False) -> list:  # type: ignore[type-arg]
        return []

    def listing_prices(self, symbol: str, listing_day: date) -> tuple[float, float] | None:
        return None


# --- the headline: passes on a working scrape, FAILS on a rotted one --------------------------


def test_selftest_passes_on_a_working_local_scrape() -> None:
    result = run_fallback_selftest(_CannedNse(), clock=lambda: _NOW)
    assert result.ok is True
    assert result.records >= 1  # the genuine build_live_records produced a valid record
    assert "reached NSE" in result.detail


def test_selftest_fails_on_a_rotted_scrape() -> None:
    result = run_fallback_selftest(_CannedNse(fail=True), clock=lambda: _NOW)
    assert result.ok is False  # the rot signal fires (this is the important half)
    assert result.records == 0


def test_selftest_fails_and_cleans_up_when_the_fallback_path_raises() -> None:
    # A non-SourceError blowing through the whole path is still caught → ok=False, not a crash.
    result = run_fallback_selftest(_CannedNse(boom=ValueError("boom")), clock=lambda: _NOW)
    assert result.ok is False
    assert "raised" in result.detail


def test_scratch_dir_is_cleaned_up(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr("ipo.service.fallback_selftest.tempfile.mkdtemp", lambda **_: str(scratch))
    run_fallback_selftest(_CannedNse(), clock=lambda: _NOW)
    assert not scratch.exists()  # rmtree'd in finally — a weekly run must never leak a scratch dir


# --- the surfacing (run_heartbeat's exit): honest naming --------------------------------------


def _result(*, ok: bool, when: datetime, records: int = 3) -> SelftestResult:
    return SelftestResult(ran_at=when, ok=ok, records=records, detail="detail")


def test_surface_passed_when_fresh_and_ok() -> None:
    row = check_selftest(_result(ok=True, when=_NOW - timedelta(days=2)), _NOW)
    assert row.status == OK and "passed" in row.detail and "3 records" in row.detail


def test_surface_failed_is_loud() -> None:
    row = check_selftest(_result(ok=False, when=_NOW - timedelta(days=1)), _NOW)
    assert (
        row.status == STALE and "FAILED" in row.detail
    )  # [STALE] local fallback - self-test FAILED


def test_surface_stale_test_is_caught() -> None:
    row = check_selftest(_result(ok=True, when=_NOW - timedelta(days=20)), _NOW)
    assert row.status == STALE and "weekly test not running" in row.detail


def test_surface_never_run_is_informational_not_an_error() -> None:
    row = check_selftest(None, _NOW)
    assert row.status == UNKNOWN and row.ok  # not deployed yet → does not fail the heartbeat


# --- persistence ------------------------------------------------------------------------------


def test_read_write_roundtrip_and_corrupt_reads_none(tmp_path: Path) -> None:
    path = tmp_path / "fallback_selftest.json"
    result = _result(ok=True, when=_NOW)
    write_selftest(path, result)
    assert read_selftest(path) == result
    path.write_text("{ truncated", encoding="utf-8")
    assert read_selftest(path) is None
    assert read_selftest(tmp_path / "nope.json") is None
