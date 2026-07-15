"""VM-primary data-plane refresh (v3 V3-1 step 2) — the honest per-store fallback + dark-ship no-op.

Asserts: VM healthy → both stores served from the VM (source=vm, freshness = the VM's timestamp);
VM down → records fall back to a real local scrape (source=local, fresh) while context keeps the
last-known cache (source=local, aging — not overwritten); and with no VM configured the cycle is a
pure local scrape that touches no context and makes no VM call.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import cast

from ipo.core.constants import IST
from ipo.core.types import IPORecord, Segment
from ipo.data.ingest.data_plane import refresh_data_plane
from ipo.data.ingest.state import IngestStateStore
from ipo.data.sources.nse import NseClient, NseSubscription
from ipo.data.store.repository import ParquetRepository
from ipo.vm.client import VmClient, VmUnavailable
from ipo.vm.models import ContextEnvelope, RecordsEnvelope

_VM_TIME = datetime(2026, 7, 14, 9, 0, tzinfo=IST)


def _record(ipo_id: str) -> IPORecord:
    return IPORecord(
        ipo_id=ipo_id,
        name=ipo_id.upper(),
        segment=Segment("mainboard"),
        price_band_low=100.0,
        price_band_high=110.0,
        open_date=date(2026, 7, 1),
        close_date=date(2026, 7, 3),
        qib_sub=3.0,
        captured_at=datetime(2026, 7, 3, 17, 0),
    )


class _FakeNse:
    """A local NSE that pulls OK but finds nothing (an empty-but-successful pull → source local)."""

    def current_issues(self) -> list[object]:
        return []

    def upcoming_issues(self) -> list[object]:
        return []

    def subscription(self, symbol: str, *, force: bool = False) -> NseSubscription:
        return NseSubscription(qib=None, nii=None, retail=None, total=None)

    def past_issues(self, *, force: bool = False) -> list[object]:
        return []

    def listing_prices(self, symbol: str, listing_day: date) -> tuple[float, float] | None:
        return None


class _FakeVm:
    def __init__(
        self, *, records: object = None, context: object = None, fail: bool = False
    ) -> None:
        self._records, self._context, self._fail = records, context, fail
        self.calls = 0

    def fetch_records(self) -> object:
        self.calls += 1
        if self._fail:
            raise VmUnavailable("vm down")
        return self._records

    def fetch_context(self) -> object:
        self.calls += 1
        if self._fail:
            raise VmUnavailable("vm down")
        return self._context


def _run(tmp: Path, vm: object) -> tuple[ParquetRepository, IngestStateStore, Path]:
    repo = ParquetRepository(tmp)
    state = IngestStateStore(tmp / "ingest_state.json")
    ctx_path = tmp / "context" / "ipo_context.json"
    refresh_data_plane(
        repo, cast(NseClient, _FakeNse()), state, ctx_path, vm_client=cast(VmClient, vm)
    )
    return repo, state, ctx_path


def test_vm_healthy_serves_both_stores_from_vm(tmp_path: Path) -> None:
    vm = _FakeVm(
        records=RecordsEnvelope(refreshed_at=_VM_TIME, records=[_record("acme")]),
        context=ContextEnvelope(refreshed_at=_VM_TIME, ipos={"ACME": {"isin": "INE0X"}}),
    )
    repo, state, ctx_path = _run(tmp_path, vm)
    assert repo.get("acme") is not None  # the VM's records were upserted
    snap = state.current()
    assert snap.source == "vm" and snap.last_success == _VM_TIME  # freshness = the VM's timestamp
    assert snap.context_source == "vm"
    assert json.loads(ctx_path.read_text())["ipos"]["ACME"]["isin"] == "INE0X"  # context written


def test_vm_down_falls_back_records_local_fresh_context_lastknown(tmp_path: Path) -> None:
    # Seed a last-known context cache; a VM outage must NOT overwrite it (can't self-refresh).
    ctx_path = tmp_path / "context" / "ipo_context.json"
    ctx_path.parent.mkdir(parents=True, exist_ok=True)
    last_known = {"refreshed_at": "2026-07-01T09:00:00+05:30", "ipos": {"OLD": {"isin": "INEOLD"}}}
    ctx_path.write_text(json.dumps(last_known), encoding="utf-8")

    _repo, state, _ = _run(tmp_path, _FakeVm(fail=True))
    snap = state.current()
    assert snap.source == "local"  # records: a real re-scrape (fresh-local)
    assert snap.context_source == "local"  # context: last-known, aging
    assert json.loads(ctx_path.read_text()) == last_known  # untouched — not overwritten


def test_dark_ship_is_local_only_no_vm_calls(tmp_path: Path) -> None:
    _repo, state, ctx_path = _run(tmp_path, None)  # no VM configured
    snap = state.current()
    assert snap.source == "local"  # pure local scrape
    assert snap.context_source is None  # context untouched (managed externally when there's no VM)
    assert not ctx_path.exists()  # the cycle wrote no context cache


def test_dark_ship_clears_stale_vm_context_source(tmp_path: Path) -> None:
    # A VM was configured before, then removed → the stale "vm" provenance must be cleared, so the
    # chip never claims "context from VM" when there is no VM.
    state = IngestStateStore(tmp_path / "ingest_state.json")
    state.record_context_source("vm")
    refresh_data_plane(
        ParquetRepository(tmp_path),
        cast(NseClient, _FakeNse()),
        state,
        tmp_path / "context" / "ipo_context.json",
        vm_client=None,
    )
    assert state.current().context_source is None
