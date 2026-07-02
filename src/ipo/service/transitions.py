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
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from ipo.core.types import VerdictType


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
        """Open (or create) the log at ``path`` and load existing transitions into memory."""
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._log: list[VerdictTransition] = []
        if self._path.is_file():
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._log = [VerdictTransition.model_validate(row) for row in raw]

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
        self._path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
