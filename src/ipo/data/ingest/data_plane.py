"""VM-primary data-plane refresh (v3 V3-1 step 2) — VM first, honest local fallback.

Each cycle fetches both stores from the VM; on any failure (unreachable, non-200, malformed) it
falls back to local and records which path served — the decision is per-cycle, so it self-heals
when the VM returns. The fallback is deliberately asymmetric, and the state reflects it honestly:

* **records** → a real NSE re-scrape (**fresh-local**);
* **context** → the last-known cache (**aging**) — the Upstox token lives on the VM, so the app
  cannot self-refresh context; it only keeps the last cache while ``field_state`` ages it.

When no VM is configured (``vm_client is None``) this is a pure local scrape — the engine behaves
exactly as before the VM existed (ships dark; the only addition is a ``source`` label on the state).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ipo.core.calendar import now_ist
from ipo.core.interfaces import Repository
from ipo.core.logging import get_logger
from ipo.data.ingest.live import refresh_from_nse
from ipo.data.ingest.state import IngestStateStore
from ipo.data.sources.nse import NseClient
from ipo.vm.client import VmClient, VmUnavailable

_log = get_logger("ipo.data.ingest.data_plane")


def refresh_data_plane(
    repo: Repository,
    nse: NseClient,
    ingest_state: IngestStateStore,
    context_path: Path,
    *,
    vm_client: VmClient | None,
    clock: Callable[[], datetime] = now_ist,
) -> None:
    """One VM-primary refresh cycle over both stores, with honest local fallback."""
    _refresh_records(repo, nse, ingest_state, vm_client, clock)
    _refresh_context(context_path, ingest_state, vm_client)


def _refresh_records(
    repo: Repository,
    nse: NseClient,
    ingest_state: IngestStateStore,
    vm_client: VmClient | None,
    clock: Callable[[], datetime],
) -> None:
    if vm_client is not None:
        try:
            envelope = vm_client.fetch_records()
            repo.upsert_many(envelope.records)
            if envelope.refreshed_at is not None:
                # The VM's own refreshed_at travels with the data — never stamped "now" (review #6).
                ingest_state.record_success(envelope.refreshed_at, source="vm")
                _log.info("records_from_vm", extra={"count": len(envelope.records)})
            else:
                # The VM responded but carries NO confirmed freshness — it never ingested, or served
                # a degraded/empty envelope (durability #2's honest refreshed_at=None). Stamping
                # success-at-now here was review #6's lie, and it silently undid #2's server-side
                # honesty. Record reachable-but-not-fresh: last_success stays honest (last-known /
                # awaiting), with no false "just refreshed" and no false "retrying".
                ingest_state.record_no_freshness(clock(), source="vm")
                _log.warning("vm_records_no_freshness", extra={"count": len(envelope.records)})
            return
        except VmUnavailable as exc:
            _log.warning("vm_records_fallback_local", extra={"error": str(exc)})
    # No VM, or the VM was unavailable → a real NSE re-scrape. refresh_from_nse records
    # success/failure into the state itself, with source defaulting to "local".
    refresh_from_nse(repo, nse, state=ingest_state)


def _refresh_context(
    context_path: Path, ingest_state: IngestStateStore, vm_client: VmClient | None
) -> None:
    if vm_client is None:
        # No VM: context is managed externally (refresh_context.py). Clear any stale VM provenance
        # (a VM that was removed) so the chip never claims "from VM"; write only if it changes.
        if ingest_state.current().context_source is not None:
            ingest_state.record_context_source(None)
        return
    try:
        envelope = vm_client.fetch_context()
        context_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic (tmp + os.replace), matching IngestStateStore._flush — ONE pattern for writing a
        # store the API thread reads, not two. This became load-bearing with BUG-4: now that
        # ContextStore re-reads the file when it changes, a plain write_text would expose a real
        # torn-read window on every cycle, where a reader could parse a half-written document. The
        # replace is what makes a reader see either the whole old file or the whole new one.
        tmp = context_path.with_suffix(context_path.suffix + ".tmp")
        tmp.write_text(envelope.model_dump_json(), encoding="utf-8")
        os.replace(tmp, context_path)
        ingest_state.record_context_source("vm")
        _log.info("context_from_vm", extra={"ipos": len(envelope.ipos)})
    except VmUnavailable as exc:
        # Cannot self-refresh (the token is on the VM) — keep the last-known cache, aging honestly.
        _log.warning("vm_context_fallback_lastknown", extra={"error": str(exc)})
        ingest_state.record_context_source("local")
