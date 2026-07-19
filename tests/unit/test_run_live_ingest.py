"""Live NSE ingest script (v3 V3-1) — writes records AND the genuine freshness clock.

The VM records timer must run the app's EXACT live path (``refresh_from_nse``), writing both
``ipo_records.parquet`` and ``ingest_state.json`` (``last_success`` / ``last_attempt_ok``) so the
read-API's ``refreshed_at`` is the real ingest time. Critically, a FAILED fetch must not advance
``last_success`` — otherwise stale data would serve under a fresh timestamp (the BUG-1 hazard, one
layer deeper). Only the NSE source is canned; the write path is genuine. Offline + deterministic.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path
from types import ModuleType

from ipo.data.ingest.state import IngestStateStore
from ipo.data.sources.base import SourceError
from ipo.data.sources.nse import (
    NseClient,
    NseCurrentIssue,
    NseSubscription,
    NseSubscriptionSnapshot,
)

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


def _load_script(name: str) -> ModuleType:
    """Load scripts/<name>.py by path (scripts is not an importable package)."""
    path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _CannedNse(NseClient):
    """A canned NSE source (no network) — fakes only the upstream data, not the write path."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    def current_issues(self, *, force: bool = True) -> list[NseCurrentIssue]:
        if self._fail:
            raise SourceError("canned: NSE feed shape changed / blocked")
        return [_ISSUE]

    def upcoming_issues(self, *, force: bool = True) -> list[NseCurrentIssue]:
        return []

    def subscription(self, symbol: str, *, force: bool = False) -> NseSubscription:
        return _SUB

    def subscription_snapshot(self, symbol: str, *, force: bool = False) -> NseSubscriptionSnapshot:
        """v3-DP DP-1: the live path now asks for the snapshot (reading + provenance).

        Delegates to this double's own canned ``subscription`` so the scoring behaviour under test
        is unchanged; ``raw_content`` is a placeholder because these tests pass no recorder sink.
        """
        return NseSubscriptionSnapshot(
            subscription=self.subscription(symbol, force=force), raw_content=b"{}"
        )

    def past_issues(self, *, force: bool = False) -> list:  # type: ignore[type-arg]
        return []

    def listing_prices(self, symbol: str, listing_day: date) -> tuple[float, float] | None:
        return None


def test_live_ingest_writes_records_and_genuine_freshness(tmp_path: Path) -> None:
    script = _load_script("run_live_ingest")
    count = script.live_ingest(_CannedNse(), tmp_path)
    assert count >= 1
    # both files land where the read-API + /status read them
    assert (tmp_path / "ipo_records.parquet").is_file()
    assert (tmp_path / "ingest_state.json").is_file()
    # the freshness state is the genuine ingest clock (what run_vm_server / /status consume)
    snap = IngestStateStore(tmp_path / "ingest_state.json").current()
    assert snap.last_attempt_ok is True
    assert snap.last_success is not None  # what the read-API serves as refreshed_at


def test_live_ingest_failure_does_not_advance_freshness(tmp_path: Path) -> None:
    # A broken/blocked NSE feed must NOT advance last_success — no stale-under-fresh-timestamp.
    script = _load_script("run_live_ingest")
    count = script.live_ingest(_CannedNse(fail=True), tmp_path)
    assert count == 0
    snap = IngestStateStore(tmp_path / "ingest_state.json").current()
    assert snap.last_attempt_ok is False
    assert snap.last_success is None  # freshness stays honest — never advanced on a failed fetch
