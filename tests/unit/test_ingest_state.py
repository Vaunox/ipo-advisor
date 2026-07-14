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
