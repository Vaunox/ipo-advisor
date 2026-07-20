"""Ingest freshness state (v3 BUG 1 / Defect 2) — the single source of truth for "how fresh".

The app must never assert a freshness it does not have. The client used to display react-query's
``dataUpdatedAt`` — "when my HTTP call to my own local sidecar last resolved" — which is always
fast and says nothing about whether NSE was actually reached. Combined with ``refresh_from_nse``
never raising, the UI could imply "just updated" while NSE had been failing for hours.

This module records the ONE clock that matters: the last time a live NSE pull genuinely succeeded.
``last_success`` advances **only** on a confirmed-good pull — never on app open, never on render,
never optimistically. Every attempt (success or failure) is recorded so a failure is visible
("last successful pull 3h ago — retrying") rather than swallowed. The state is persisted so a cold
boot whose first pull fails still reports the truthful last-success time from a prior session,
instead of implying freshness.

Thread-safe: the scheduler thread and the shell-triggered refresh both write; the API thread reads.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from ipo.core.logging import get_logger

_log = get_logger("ipo.data.ingest.state")


class IngestState(BaseModel):
    """A point-in-time snapshot of live-ingest freshness.

    ``last_success`` is the timestamp of the last *confirmed-good* NSE pull — the only value the UI
    may present as "updated". ``last_attempt`` / ``last_attempt_ok`` describe the most recent try
    (which may have failed while ``last_success`` stays put), so the UI can honestly show a stale +
    retrying state. ``last_error`` is a short diagnostic for logs/operators, not a user promise.
    """

    last_success: datetime | None = None
    last_attempt: datetime | None = None
    last_attempt_ok: bool | None = None
    last_error: str | None = None
    # v3 V3-1: which path served each store this cycle — "vm" | "local" | None (no VM configured).
    # Provenance labels only; freshness still lives on ``last_success`` (records) and the context
    # cache's own ``refreshed_at`` (one staleness rule, not a second freshness path). They differ in
    # fallback: records → fresh-local (re-scrape), context → last-known-aging (the Upstox token is
    # on the VM, so the app cannot self-refresh context — it only keeps serving the last cache).
    source: str | None = None
    context_source: str | None = None


class IngestStateStore:
    """Durable, thread-safe holder of :class:`IngestState`, persisted as a small JSON file.

    One instance is shared in-process between the refresh path (writer) and the ``/status`` reader.
    Held in memory under a lock and rewritten atomically on each update (tmp + ``os.replace``) so a
    concurrent read never sees a torn file. Loaded from disk at construction so freshness survives a
    restart — a cold boot before its first successful pull reports the last real success, not a lie.
    """

    def __init__(self, path: Path) -> None:
        """Open (or create) the state file at ``path`` and load any prior state into memory."""
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._state = IngestState()
        # v3 QoL: when the next scheduled refresh fires. IN-MEMORY ONLY (never persisted) — a live
        # schedule fact that must not survive a restart (a reboot perturbs the cadence), and is None
        # whenever the next tick can't be honestly predicted (failing feed, fallback, or right after
        # a manual refresh) so the UI shows nothing rather than a guess.
        self._next_refresh: datetime | None = None
        if self._path.is_file():
            try:
                self._state = IngestState.model_validate_json(
                    self._path.read_text(encoding="utf-8")
                )
            except (ValueError, OSError) as exc:  # corrupt/partial file → start clean, don't crash
                _log.warning("ingest_state_load_failed", extra={"error": str(exc)})

    def record_success(self, when: datetime, *, source: str = "local") -> None:
        """Advance freshness to ``when`` — a good records fetch (``source``: vm | local).

        ``when`` is the served data's own timestamp: the VM's ``refreshed_at`` when the VM served,
        the local pull time when we scraped — one staleness rule reasons about both paths the same.
        ``model_copy`` preserves ``context_source`` (recorded separately in the same cycle).
        """
        with self._lock:
            self._state = self._state.model_copy(
                update={
                    "last_success": when,
                    "last_attempt": when,
                    "last_attempt_ok": True,
                    "last_error": None,
                    "source": source,
                }
            )
            self._flush()

    def record_context_source(self, source: str | None) -> None:
        """Record which path (vm | local | None) served the context store this cycle.

        Freshness is the context cache's own ``refreshed_at`` (read by ``field_state``), not here.
        ``None`` clears stale provenance (e.g. a VM was removed) so the chip never claims "from VM"
        when there is no VM.
        """
        with self._lock:
            self._state = self._state.model_copy(update={"context_source": source})
            self._flush()

    def record_failure(self, when: datetime, error: str) -> None:
        """Record a failed attempt at ``when`` — ``last_success`` is untouched (honestly stale)."""
        with self._lock:
            self._state = self._state.model_copy(
                update={
                    "last_attempt": when,
                    "last_attempt_ok": False,
                    "last_error": error[:200],
                }
            )
            self._flush()

    def record_no_freshness(self, when: datetime, *, source: str = "vm") -> None:
        """Record a REACHABLE cycle that carried NO fresh data (``last_success`` left untouched).

        The VM-primary path calls this when the VM responds but its envelope has ``refreshed_at``
        None — the VM never ingested, or served a degraded/empty envelope (durability #2's honest
        null). The data is NOT fresh, so ``last_success`` must not advance to now: stamping now was
        review #6's freshness lie, and it silently undid #2's server-side honesty. But the call WAS
        reachable, so this is NOT a failure — ``last_attempt_ok`` stays True and ``last_error``
        clears, so the chip reads "awaiting first update" / last-known, never "retrying" (which
        ``record_failure`` would wrongly show). ``source`` is recorded since the VM did serve.
        """
        with self._lock:
            self._state = self._state.model_copy(
                update={
                    "last_attempt": when,
                    "last_attempt_ok": True,
                    "last_error": None,
                    "source": source,
                }
            )
            self._flush()

    def current(self) -> IngestState:
        """The current freshness snapshot (a copy — safe to serialize on the API thread)."""
        with self._lock:
            return self._state.model_copy()

    def set_next_refresh(self, when: datetime | None) -> None:
        """Record when the next scheduled refresh fires, or ``None`` when it can't be honestly set.

        In-memory only (not flushed): a live schedule fact, not persisted freshness. ``None`` is the
        honest default — a next-refresh hint shows only when a clean, regular cadence holds.
        """
        with self._lock:
            self._next_refresh = when

    def next_refresh(self) -> datetime | None:
        """The next scheduled refresh time, or ``None`` if it can't be honestly predicted."""
        with self._lock:
            return self._next_refresh

    def _flush(self) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(self._state.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, self._path)  # atomic swap so a concurrent reader never sees a partial write
