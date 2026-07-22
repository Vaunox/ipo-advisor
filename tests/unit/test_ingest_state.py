"""Ingest freshness state (v3 BUG 1 / Defect 2) — the honest last-successful-pull clock.

The store must advance ``last_success`` ONLY on a confirmed-good pull, keep it stale (untouched)
across failures while recording the failed attempt, and survive a restart (so a cold boot with a
failing first pull reports the real prior success, not a lie). Offline + deterministic.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ipo.data.ingest.state import IngestState, IngestStateStore


def test_starts_empty(tmp_path: Path) -> None:
    s = IngestStateStore(tmp_path / "ingest_state.json").current()
    assert s == IngestState()  # all None — no freshness asserted before a real pull
    assert s.last_success is None and s.last_attempt is None and s.last_attempt_ok is None


def test_success_advances_last_success(tmp_path: Path) -> None:
    store = IngestStateStore(tmp_path / "ingest_state.json")
    t = datetime(2026, 7, 14, 9, 0)
    store.record_success(t)
    s = store.current()
    assert s.last_success == t
    assert s.last_attempt == t
    assert s.last_attempt_ok is True
    assert s.last_error is None


def test_failure_records_attempt_but_not_success(tmp_path: Path) -> None:
    store = IngestStateStore(tmp_path / "ingest_state.json")
    ok_t = datetime(2026, 7, 14, 9, 0)
    fail_t = datetime(2026, 7, 14, 12, 0)
    store.record_success(ok_t)
    store.record_failure(fail_t, "nse unreachable")
    s = store.current()
    # last_success stays put (still 9:00) — the store is stale but never lies about being fresh
    assert s.last_success == ok_t
    assert s.last_attempt == fail_t  # the failed attempt IS recorded (visible, not swallowed)
    assert s.last_attempt_ok is False
    assert s.last_error == "nse unreachable"


def test_failure_before_any_success_leaves_success_none(tmp_path: Path) -> None:
    store = IngestStateStore(tmp_path / "ingest_state.json")
    store.record_failure(datetime(2026, 7, 14, 8, 0), "cookie handshake failed")
    s = store.current()
    assert s.last_success is None  # never claim freshness we never had
    assert s.last_attempt_ok is False


# --- OP-2 Phase 2: the app's-last-successful-PULL clock (last_pull_ok) — the honest "Checked" time.


def test_success_advances_last_pull_ok_defaulting_to_when(tmp_path: Path) -> None:
    # For the local scrape, the served-data time IS the pull time, so pulled_at defaults to `when`.
    store = IngestStateStore(tmp_path / "ingest_state.json")
    t = datetime(2026, 7, 14, 9, 0)
    store.record_success(t)
    assert store.current().last_pull_ok == t


def test_success_pull_clock_is_distinct_from_the_data_clock(tmp_path: Path) -> None:
    # The VM path: `when` is the VM's (older) refreshed_at; pulled_at is when the app pulled (now).
    # The two clocks must NOT be conflated — last_success is the data time, last_pull_ok the pull.
    store = IngestStateStore(tmp_path / "ingest_state.json")
    data_ts = datetime(2026, 7, 14, 9, 0)
    pulled = datetime(2026, 7, 14, 9, 27)
    store.record_success(data_ts, source="vm", pulled_at=pulled)
    s = store.current()
    assert s.last_success == data_ts  # the served data's own timestamp (the VM's refreshed_at)
    assert s.last_pull_ok == pulled  # the app's pull wall-clock — the "Checked HH:MM" the UI shows


def test_no_freshness_advances_the_pull_clock_but_not_the_data_clock(tmp_path: Path) -> None:
    # Reachable VM that served records with no fresh stamp: "I checked at HH:MM" is true, so the
    # pull clock advances, while last_success stays honestly null (review #6). Endorsed in Phase 2.
    store = IngestStateStore(tmp_path / "ingest_state.json")
    checked = datetime(2026, 7, 14, 9, 30)
    store.record_no_freshness(checked, source="vm")
    s = store.current()
    assert s.last_pull_ok == checked  # the app did successfully check
    assert s.last_success is None  # but the data itself carried no fresh timestamp


def test_failure_never_advances_the_pull_clock(tmp_path: Path) -> None:
    # A failed pull must not overwrite the honest last-check time with a fresh lie (Checked 12:00
    # when nothing was fetched). last_pull_ok stays at the prior success.
    store = IngestStateStore(tmp_path / "ingest_state.json")
    ok_t = datetime(2026, 7, 14, 9, 0)
    store.record_success(ok_t)
    store.record_failure(datetime(2026, 7, 14, 12, 0), "nse unreachable")
    assert store.current().last_pull_ok == ok_t  # unchanged — never advances on failure


def test_pull_clock_none_before_any_pull_then_persists(tmp_path: Path) -> None:
    path = tmp_path / "ingest_state.json"
    assert IngestStateStore(path).current().last_pull_ok is None  # honest — no check yet
    t = datetime(2026, 7, 14, 9, 0)
    IngestStateStore(path).record_success(t)
    assert IngestStateStore(path).current().last_pull_ok == t  # survives a restart, like the rest


def test_persists_across_reload(tmp_path: Path) -> None:
    path = tmp_path / "ingest_state.json"
    t = datetime(2026, 7, 14, 9, 0)
    IngestStateStore(path).record_success(t)
    # A brand-new instance (simulating a process restart) reads the durable last success.
    reloaded = IngestStateStore(path).current()
    assert reloaded.last_success == t
    assert reloaded.last_attempt_ok is True


def test_reload_after_failure_keeps_prior_success(tmp_path: Path) -> None:
    """A cold boot whose first pull fails still reports the real prior success time, not a lie."""
    path = tmp_path / "ingest_state.json"
    ok_t = datetime(2026, 7, 14, 9, 0)
    IngestStateStore(path).record_success(ok_t)
    IngestStateStore(path).record_failure(datetime(2026, 7, 14, 12, 0), "down")
    reloaded = IngestStateStore(path).current()
    assert reloaded.last_success == ok_t  # honest "last successful pull 9:00 AM"
    assert reloaded.last_attempt_ok is False


def test_corrupt_file_starts_clean(tmp_path: Path) -> None:
    path = tmp_path / "ingest_state.json"
    path.write_text("{ not valid json", encoding="utf-8")
    # A partial/corrupt file must not crash the engine — start clean rather than raise.
    assert IngestStateStore(path).current() == IngestState()


def test_next_refresh_defaults_none_and_round_trips(tmp_path: Path) -> None:
    store = IngestStateStore(tmp_path / "ingest_state.json")
    assert (
        store.next_refresh() is None
    )  # honest default — no prediction until a clean cycle sets one
    t = datetime(2026, 7, 14, 9, 30)
    store.set_next_refresh(t)
    assert store.next_refresh() == t
    store.set_next_refresh(None)  # a manual refresh / fallback clears it → tooltip shows nothing
    assert store.next_refresh() is None


def test_next_refresh_is_in_memory_only_not_persisted(tmp_path: Path) -> None:
    # The next-refresh time is a live schedule fact that must NOT survive a restart (a reboot
    # perturbs the cadence). A fresh store from the same file must not resurrect a stale value.
    path = tmp_path / "ingest_state.json"
    store = IngestStateStore(path)
    store.record_success(datetime(2026, 7, 14, 9, 0))  # persisted freshness
    store.set_next_refresh(datetime(2026, 7, 14, 9, 30))  # in-memory only
    reloaded = IngestStateStore(path)
    assert reloaded.current().last_success == datetime(2026, 7, 14, 9, 0)  # freshness survived
    assert reloaded.next_refresh() is None  # the next-refresh prediction did NOT (correct)
