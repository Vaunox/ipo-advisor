"""Weekly fallback self-test (v3 V3-4) — prove the local-scrape path still works while the VM is up.

V3-1 owns the fallback client; this is the periodic PROOF it hasn't rotted. It drives the GENUINE
local path — only the *trigger* is faked: a ``VmClient`` that raises ``VmUnavailable``, exactly as a
down VM would, so ``refresh_data_plane`` takes its ``except VmUnavailable`` branch into
``refresh_from_nse`` → ``build_live_records`` → the real ``NseClient`` → real NSE → validation →
write. No manufactured outage: the VM can be up and serving; this exercises the local branch on
demand into a throwaway store, which is always cleaned up.

The verdict is recorded to a small file that ``run_heartbeat --fallback-selftest`` reads, so a
rotted fallback surfaces in the ritual you already run (fail loud) — and a self-test that stops
running is itself caught (staleness on the result).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ValidationError

from ipo.core.calendar import now_ist
from ipo.data.ingest.data_plane import refresh_data_plane
from ipo.data.ingest.state import IngestStateStore
from ipo.data.sources.nse import NseClient
from ipo.data.store.repository import ParquetRepository
from ipo.service.heartbeat import OK, STALE, UNKNOWN, FeedHealth, ago
from ipo.vm.client import VmClient, VmUnavailable
from ipo.vm.models import ContextEnvelope, RecordsEnvelope

SELFTEST_MAX_AGE = timedelta(days=10)  # weekly cadence + buffer before "the test stopped running"


class SelftestResult(BaseModel):
    """The recorded verdict of one fallback self-test run."""

    ran_at: datetime
    ok: bool
    records: int
    detail: str


class _ForcedDownVm(VmClient):
    """The self-test's TRIGGER: a ``VmClient`` that is always "down".

    Only the trigger is faked (the fetches raise ``VmUnavailable``, exactly as a real down VM does);
    the local fallback it forces — ``refresh_from_nse`` → the real ``NseClient`` → NSE — is genuine.
    """

    def __init__(self) -> None:
        super().__init__("http://fallback-selftest.invalid")

    def fetch_records(self) -> RecordsEnvelope:
        raise VmUnavailable("fallback self-test: forcing the local records fallback")

    def fetch_context(self) -> ContextEnvelope:
        raise VmUnavailable("fallback self-test: forcing the local context fallback")


def run_fallback_selftest(
    nse: NseClient, *, clock: Callable[[], datetime] = now_ist
) -> SelftestResult:
    """Drive the genuine local fallback into a throwaway store; record if it produced valid data.

    The scratch store is isolated (its own temp dir, never the live ``data_store/``) and ALWAYS
    cleaned up in ``finally`` — a weekly run must never leak a scratch dir (that slow-fills disk).
    The ``nse`` is injected so production passes the real polite client and tests pass a canned one;
    the fallback code it drives is real either way.
    """
    ran_at = clock()
    scratch = Path(tempfile.mkdtemp(prefix="ipo-fallback-selftest-"))
    try:
        repo = ParquetRepository(scratch)
        state = IngestStateStore(scratch / "ingest_state.json")
        context_path = scratch / "context" / "ipo_context.json"
        try:
            refresh_data_plane(
                repo, nse, state, context_path, vm_client=_ForcedDownVm(), clock=clock
            )
        except Exception as exc:  # noqa: BLE001 — a broken fallback path IS the rot this tests for
            return SelftestResult(
                ran_at=ran_at,
                ok=False,
                records=0,
                detail=f"fallback path raised {type(exc).__name__}: {exc}",
            )
        snap = state.current()
        records = len(repo.list_all())
        ok = bool(snap.last_attempt_ok) and snap.source == "local"
        if ok:
            detail = f"local scrape reached NSE and validated {records} record(s)"
        else:
            why = snap.last_error or "no successful pull recorded"
            detail = f"local scrape did not confirm a good NSE pull ({why})"
        return SelftestResult(ran_at=ran_at, ok=ok, records=records, detail=detail)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)  # never leak a scratch dir, even on failure


def read_selftest(path: Path) -> SelftestResult | None:
    """Load the last verdict (``None`` if absent/corrupt → the detector treats it as stale)."""
    if not path.is_file():
        return None
    try:
        return SelftestResult.model_validate_json(path.read_text(encoding="utf-8-sig"))
    except (ValueError, ValidationError):
        return None


def write_selftest(path: Path, result: SelftestResult) -> None:
    """Atomically record the verdict (tmp + ``os.replace``) for ``run_heartbeat`` to read."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)


def check_selftest(
    result: SelftestResult | None, now: datetime, *, max_age: timedelta = SELFTEST_MAX_AGE
) -> FeedHealth:
    """Judge the recorded verdict, naming the failure honestly (drives run_heartbeat's exit).

    Never run (absent) is informational (not deployed); a FAILED run or a STALE one (the weekly test
    stopped) both fail loud.
    """
    if result is None:
        return FeedHealth("local fallback", UNKNOWN, "self-test has not run yet (not deployed?)")
    age = now - result.ran_at
    if not result.ok:
        return FeedHealth(
            "local fallback", STALE, f"self-test FAILED {ago(age)} ago: {result.detail}"
        )
    if age > max_age:
        return FeedHealth(
            "local fallback",
            STALE,
            f"self-test stale (last run {ago(age)} ago) — weekly test not running?",
        )
    return FeedHealth(
        "local fallback", OK, f"self-test passed {ago(age)} ago ({result.records} records)"
    )
