"""Scheduler — windowed score cadence with idempotent cycles (Phase 6 step 4).

Runs the engine on a cadence: every ~6h normally, every ~30min while a subscription book is
open (where verdicts move). A cycle is (optional refresh) → score → diff against the prior
cycle's verdicts. Three properties it guarantees:

* **Idempotent.** Running a cycle twice over unchanged state yields identical verdicts and NO
  repeated transitions — so step 5 will not re-alert every cycle while a book stays open.
* **Transition-tracked.** It records each IPO's prior verdict, so a crossing INTO APPLY is
  emitted once (in ``CycleResult.became_apply``); staying APPLY emits nothing. Step 5 fires on
  that crossing, not on the steady state.
* **As-of now.** A cycle scores point-in-time: the engine reads only data dated at/before its
  clock (``market_regime`` included), so a scheduled run never sees the future.

Advisory only: the scheduler scores and flags; it never places an order. Live GMP stays absent
(0 contribution) until it earns its place (docs/GMP_GATE.md).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from ipo.core.calendar import now_ist
from ipo.core.config import AppConfig
from ipo.core.types import IPORecord, Verdict, VerdictType


@runtime_checkable
class VerdictSource(Protocol):
    """What the scheduler reads: verdicts for all stored IPOs, and the records (for cadence)."""

    def verdicts(self, *, asof: datetime | None = None) -> list[Verdict]:
        """Verdicts for all stored IPOs, scored point-in-time."""
        ...

    def records(self) -> list[IPORecord]:
        """All stored IPO records."""
        ...


@dataclass(frozen=True)
class CycleResult:
    """One scheduler cycle: when it ran, the verdicts, and the APPLY crossings to notify."""

    asof: datetime
    verdicts: list[Verdict]
    became_apply: list[str]  # ipo_ids that crossed INTO APPLY this cycle (for step-5 notify)


class ScoringScheduler:
    """Drives windowed, idempotent scoring cycles over a ``VerdictSource``."""

    def __init__(
        self,
        *,
        source: VerdictSource,
        config: AppConfig,
        refresh: Callable[[], None] | None = None,
        clock: Callable[[], datetime] = now_ist,
    ) -> None:
        """Bind the verdict source, cadence config, optional refresh hook, and clock."""
        self._source = source
        self._config = config
        self._refresh = refresh
        self._clock = clock
        self._last_verdict: dict[str, VerdictType] = {}

    def run_cycle(self) -> CycleResult:
        """Refresh (if wired), score, and emit the APPLY crossings since the last cycle.

        Idempotent: a second cycle over unchanged state returns the same verdicts and an empty
        ``became_apply`` (the prior-state map already reflects them), so no duplicate alerts.
        """
        when = self._clock()
        if self._refresh is not None:
            self._refresh()
        verdicts = self._source.verdicts()
        became_apply: list[str] = []
        for verdict in verdicts:
            prior = self._last_verdict.get(verdict.ipo_id)
            if verdict.verdict is VerdictType.APPLY and prior is not VerdictType.APPLY:
                became_apply.append(verdict.ipo_id)
            self._last_verdict[verdict.ipo_id] = verdict.verdict
        return CycleResult(asof=when, verdicts=verdicts, became_apply=became_apply)

    def next_cadence_minutes(self) -> int:
        """30 min while any subscription book is open (verdicts move), else the default ~6h."""
        day = self._clock().date()
        scrape = self._config.scrape
        book_open = any(r.open_date <= day <= r.close_date for r in self._source.records())
        return (
            scrape.cadence_minutes_subscription_window
            if book_open
            else scrape.cadence_minutes_default
        )
