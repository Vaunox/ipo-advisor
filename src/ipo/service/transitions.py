"""Durable verdict-transition log (Phase 7) — the history behind the alert center + detail log.

A verdict is a point-in-time snapshot; *when it changed* is temporal and cannot be re-derived
from a single read, so transitions must be recorded as they happen. The scheduler already
diffs each cycle against the prior verdict (that is how it de-duplicates alerts); this store is
the thin, append-only persistence of those diffs so the API can serve an honest history that
survives restarts.

It records only genuine changes (a differing prior verdict), never a re-score: every
``to_verdict`` / ``probability`` is exactly what the engine emitted at ``asof``. Advisory only —
a transition is a logged observation, never an action (Inviolable Rule 6).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from ipo.core.logging import get_logger
from ipo.core.types import VerdictType

_log = get_logger("ipo.service.transitions")


class VerdictTransition(BaseModel):
    """One recorded verdict change for an IPO: prior → current at a decision clock.

    ``from_verdict`` is ``None`` only for a first observation. ``crossed_into_apply`` marks the
    APPLY crossing the alert center fires on (current APPLY, prior not APPLY) — the same crossing
    the notifier uses, so the log and the alerts never disagree.
    """

    ipo_id: str
    asof: datetime
    from_verdict: VerdictType | None
    to_verdict: VerdictType
    probability: float | None
    crossed_into_apply: bool


class TransitionStore:
    """Append-only JSON log of ``VerdictTransition``s, keyed by insertion order.

    Tiny by construction (a handful of transitions per IPO over its lifecycle), so the whole log
    is held in memory and rewritten on append — the simplest design that is durable and ordered.
    """

    def __init__(self, path: Path) -> None:
        """Open (or create) the log at ``path`` and load existing transitions into memory.

        A corrupt/truncated log must NOT crash engine boot: this runs in the constructor, so a raise
        here would take the whole engine down (the defect the code review raised as #3). Instead a
        bad file is moved aside — its bytes kept for inspection — and we start empty with a loud
        WARN. See :meth:`_load_or_start_empty`.
        """
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._log: list[VerdictTransition] = self._load_or_start_empty()

    def _load_or_start_empty(self) -> list[VerdictTransition]:
        """Load the persisted log, or degrade to empty (never raise) if it cannot be read.

        The transition log is NON-REPRODUCIBLE — *when* a verdict changed cannot be re-derived from
        a single read — and it has NO backup anywhere (the V3-2 archive mirrors only records +
        context, not this file). So a corrupt file's bytes are quarantined aside for inspection,
        not silently overwritten by the next ``_flush``; but the history before the corruption is
        unrecoverable, and the WARN says so straight rather than pointing at an archive that does
        not hold it. Forward history rebuilds from the next verdict cycle and the advice is
        unaffected (verdicts are re-derived live from the records). Starting empty re-primes the
        scheduler from scratch, which can re-record/re-alert already-known verdicts (OP-3) — the
        accepted price of never blocking boot, logged loudly rather than hidden.
        """
        if not self._path.is_file():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8-sig"))  # -sig tolerates a BOM
            if not isinstance(raw, list):
                raise ValueError(f"transition log is not a JSON array: {type(raw).__name__}")
            return [VerdictTransition.model_validate(row) for row in raw]
        except (OSError, ValueError, ValidationError) as exc:
            self._quarantine_corrupt(exc)
            return []

    def _quarantine_corrupt(self, exc: Exception) -> None:
        """Move an unreadable log aside (best-effort) and WARN, naming the recovery path.

        Moving it rather than leaving it is what makes start-empty safe: the next ``_flush`` does an
        atomic ``os.replace`` onto ``self._path`` and would otherwise erase the corrupt bytes we
        want kept. If the move itself fails we still start empty (never raise) and log that too.
        """
        quarantine = self._path.with_suffix(self._path.suffix + ".corrupt")
        moved: str | None = None
        try:
            os.replace(self._path, quarantine)  # overwrites any prior quarantine; newest wins
            moved = str(quarantine)
        except OSError as move_exc:
            _log.warning(
                "verdict_transition_log_quarantine_failed",
                extra={"path": str(self._path), "error": str(move_exc)},
            )
        _log.warning(
            "verdict_transition_log_corrupt",
            extra={
                "path": str(self._path),
                "error": str(exc),
                "quarantined_to": moved,
                "impact": (
                    "history reset to empty; the scheduler re-primes and may re-record/re-alert "
                    "known verdicts (OP-3)"
                ),
                "recoverability": (
                    "the transition history before this point is UNRECOVERABLE — no backup of "
                    "verdict_transitions.json exists anywhere (the V3-2 archive mirrors only "
                    "records + context). Forward history rebuilds from the next verdict cycle; "
                    "advice is unaffected — verdicts are re-derived live from the records."
                ),
            },
        )

    def record(self, transition: VerdictTransition) -> None:
        """Append one transition and flush (durable)."""
        self._log.append(transition)
        self._flush()

    def all(self) -> list[VerdictTransition]:
        """Every recorded transition, most-recent-first."""
        return sorted(self._log, key=lambda t: t.asof, reverse=True)

    def for_ipo(self, ipo_id: str) -> list[VerdictTransition]:
        """Transitions for one IPO, most-recent-first."""
        return [t for t in self.all() if t.ipo_id == ipo_id]

    def latest_by_ipo(self) -> dict[str, VerdictType]:
        """Each IPO's most recent ``to_verdict``.

        Used to prime the scheduler so a restart does not re-record verdicts already known — only
        genuine future changes are logged (no duplicate history).
        """
        latest: dict[str, VerdictTransition] = {}
        for t in self._log:
            prev = latest.get(t.ipo_id)
            if prev is None or t.asof >= prev.asof:
                latest[t.ipo_id] = t
        return {ipo_id: t.to_verdict for ipo_id, t in latest.items()}

    def _flush(self) -> None:
        rows = [t.model_dump(mode="json") for t in self._log]
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)  # atomic swap — a crash/concurrent read never sees a torn file
