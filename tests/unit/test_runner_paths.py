"""Phase 7 packaging: the sidecar's store provisioning is dev-safe, versioned, and idempotent.

Provisioning only runs for the packaged app (``manage=True``); dev-from-source is a no-op so the
developer's ``data_store`` is never touched. When managing, it is **versioned** (``_SEED_VERSION``):
a fresh install or an update that changed the shipped data clears the old store so stale/demo
records don't persist; an unchanged version keeps the user's live-accumulated data. A live-only
build ships no seed, so a mismatch just clears the store and live ingestion refills it.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import pytest

from ipo.service.runner import (
    _FAILSAFE_CADENCE_MIN,
    _SEED_VERSION,
    _provision_data_dir,
    _run_cycle_guarded,
)


def _make_seed(resource_root: Path) -> None:
    seed = resource_root / "_seed"
    seed.mkdir(parents=True)
    (seed / "ipo_records.parquet").write_bytes(b"SEED-PARQUET")
    (seed / "verdict_transitions.json").write_text("[]", encoding="utf-8")


def test_dev_is_a_noop(tmp_path: Path) -> None:
    res = tmp_path / "bundle"
    _make_seed(res)
    data_dir = tmp_path / "userdata"
    data_dir.mkdir()
    (data_dir / "ipo_records.parquet").write_bytes(b"DEV-DATA")

    _provision_data_dir(data_dir, res, manage=False)  # dev-from-source

    assert (data_dir / "ipo_records.parquet").read_bytes() == b"DEV-DATA"  # untouched
    assert not (data_dir / "seed_version").exists()


def test_provisions_empty_data_dir(tmp_path: Path) -> None:
    res = tmp_path / "bundle"
    _make_seed(res)
    data_dir = tmp_path / "userdata"

    _provision_data_dir(data_dir, res, manage=True)

    assert (data_dir / "ipo_records.parquet").read_bytes() == b"SEED-PARQUET"
    assert (data_dir / "seed_version").read_text(encoding="utf-8") == _SEED_VERSION


def test_keeps_data_when_version_matches(tmp_path: Path) -> None:
    res = tmp_path / "bundle"
    _make_seed(res)
    data_dir = tmp_path / "userdata"
    data_dir.mkdir()
    (data_dir / "ipo_records.parquet").write_bytes(b"LIVE-DATA")  # user's accumulated store
    (data_dir / "seed_version").write_text(_SEED_VERSION, encoding="utf-8")  # up to date

    _provision_data_dir(data_dir, res, manage=True)

    assert (data_dir / "ipo_records.parquet").read_bytes() == b"LIVE-DATA"  # kept, not clobbered


def test_clears_stale_data_on_version_mismatch(tmp_path: Path) -> None:
    res = tmp_path / "bundle"
    _make_seed(res)
    data_dir = tmp_path / "userdata"
    data_dir.mkdir()
    (data_dir / "ipo_records.parquet").write_bytes(b"OLD-DEMO")  # from a previous install
    # no seed_version marker → stale

    _provision_data_dir(data_dir, res, manage=True)

    assert (data_dir / "ipo_records.parquet").read_bytes() == b"SEED-PARQUET"  # re-provisioned
    assert (data_dir / "seed_version").read_text(encoding="utf-8") == _SEED_VERSION


def test_live_only_clears_stale_without_seed(tmp_path: Path) -> None:
    res = tmp_path / "bundle"  # no _seed/ (live-only build)
    res.mkdir()
    data_dir = tmp_path / "userdata"
    data_dir.mkdir()
    (data_dir / "ipo_records.parquet").write_bytes(b"OLD-DEMO")  # stale from an older install

    _provision_data_dir(data_dir, res, manage=True)

    # No seed to restore → the stale store is cleared (live ingest will refill it) and marked.
    assert not (data_dir / "ipo_records.parquet").exists()
    assert (data_dir / "seed_version").read_text(encoding="utf-8") == _SEED_VERSION


def test_clearing_the_store_on_a_version_bump_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # A4: a version bump DELETES the store + history — it must not do so silently.
    res = tmp_path / "bundle"
    _make_seed(res)
    data_dir = tmp_path / "userdata"
    data_dir.mkdir()
    (data_dir / "ipo_records.parquet").write_bytes(b"OLD-DEMO")  # user/demo data about to be wiped

    with caplog.at_level(logging.WARNING, logger="ipo.service.runner"):
        _provision_data_dir(data_dir, res, manage=True)

    cleared = [
        r for r in caplog.records if r.getMessage() == "data_store_cleared_on_version_change"
    ]
    assert len(cleared) == 1
    assert "ipo_records.parquet" in cleared[0].__dict__["cleared"]


# --- B1/B2: the scheduler loop survives a raising cycle instead of dying silently ----------------


class _OkService:
    """Test shim: a service whose cycle succeeds and reports a windowed cadence."""

    def __init__(self, cadence: int) -> None:
        self._cadence = cadence
        self.cycles = 0
        self.scheduler = self  # run_cycle + next_cadence_minutes on one object (test double)

    def run_cycle(self) -> None:
        self.cycles += 1

    def next_cadence_minutes(self) -> int:
        return self._cadence


class _BoomService:
    """Test shim: a service whose cycle raises — the previously-fatal case B1 fixes."""

    def __init__(self) -> None:
        self.cycles = 0
        self.scheduler = self

    def run_cycle(self) -> None:
        self.cycles += 1
        raise RuntimeError("disk full during parquet flush")

    def next_cadence_minutes(self) -> int:  # pragma: no cover - never reached on the boom path
        raise AssertionError("cadence must not be consulted after a failed cycle")


def test_run_cycle_guarded_returns_windowed_cadence_on_success() -> None:
    service = _OkService(cadence=360)
    assert _run_cycle_guarded(service, threading.Lock()) == 360  # scheduler's own cadence
    assert service.cycles == 1


def test_run_cycle_guarded_survives_a_raising_cycle(caplog: pytest.LogCaptureFixture) -> None:
    # Before B1 this exception propagated out of loop() and killed the daemon thread silently.
    service = _BoomService()
    lock = threading.Lock()
    with caplog.at_level(logging.ERROR):
        cadence = _run_cycle_guarded(service, lock)  # must NOT raise
    assert service.cycles == 1  # the cycle was attempted
    assert cadence == _FAILSAFE_CADENCE_MIN  # loop backs off, then continues — never wedges
    failures = [r for r in caplog.records if r.getMessage() == "scheduler_cycle_failed"]
    assert len(failures) == 1  # the death is now loud, not silent
    assert "disk full" in str(failures[0].__dict__["error"])
    assert lock.acquire(blocking=False)  # the lock was released despite the raise
    lock.release()


def test_scheduler_survives_to_run_the_next_cycle() -> None:
    # The headline guarantee: one bad cycle does not stop the scheduler — the next cycle still runs.
    assert _run_cycle_guarded(_BoomService(), threading.Lock()) == _FAILSAFE_CADENCE_MIN
    ok = _OkService(cadence=30)
    assert _run_cycle_guarded(ok, threading.Lock()) == 30  # the following cycle runs normally
    assert ok.cycles == 1
