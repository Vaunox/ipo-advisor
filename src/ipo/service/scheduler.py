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
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from ipo.core.calendar import now_ist
from ipo.core.config import AppConfig
from ipo.core.logging import get_logger
from ipo.core.types import IPORecord, Verdict, VerdictType
from ipo.service.lifecycle import listing_overdue_state
from ipo.service.transitions import VerdictTransition

_log = get_logger("ipo.service.scheduler")


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
        on_transition: Callable[[VerdictTransition], None] | None = None,
        initial_last: dict[str, VerdictType] | None = None,
        clock: Callable[[], datetime] = now_ist,
    ) -> None:
        """Bind the verdict source, cadence config, optional refresh + transition hooks, and clock.

        ``initial_last`` primes the prior-verdict map (from the persisted transition log), so a
        restart does not re-record verdicts already known — only genuine future changes are logged.
        """
        self._source = source
        self._config = config
        self._refresh = refresh
        self._on_transition = on_transition
        self._clock = clock
        self._last_verdict: dict[str, VerdictType] = dict(initial_last or {})
        # finding-④: ipo_id -> last overdue-listing state, so a strand is logged once when it
        # crosses into overdue (or changes mode), never re-logged while it stays overdue.
        self._overdue_state: dict[str, str] = {}

    def run_cycle(self) -> CycleResult:
        """Refresh (if wired), score, and emit the APPLY crossings since the last cycle.

        Idempotent: a second cycle over unchanged state returns the same verdicts and an empty
        ``became_apply`` (the prior-state map already reflects them), so no duplicate alerts. A
        genuine verdict change (differing prior) is recorded to the transition hook once — never
        the steady state, so the durable log inherits the same no-duplicate guarantee.
        """
        when = self._clock()
        _log.info("scheduler_cycle_start", extra={"asof": when.isoformat()})
        if self._refresh is not None:
            self._refresh()
        verdicts = self._source.verdicts()
        became_apply: list[str] = []
        n_transitions = 0
        for verdict in verdicts:
            prior = self._last_verdict.get(verdict.ipo_id)
            crossed = verdict.verdict is VerdictType.APPLY and prior is not VerdictType.APPLY
            if crossed:
                became_apply.append(verdict.ipo_id)
            # A first observation that is merely abstaining (None -> INSUFFICIENT_SIGNAL) is not a
            # meaningful change — starting to watch an open book is not an event to log.
            first_abstention = prior is None and verdict.verdict is VerdictType.INSUFFICIENT_SIGNAL
            changed = prior != verdict.verdict and not first_abstention
            if changed:
                # The verdict-emission narrative: a genuine change, logged INDEPENDENTLY of the
                # notify channel (which may be off) so the console always shows what the engine did.
                n_transitions += 1
                _log.info(
                    "verdict_transition",
                    extra={
                        "ipo_id": verdict.ipo_id,
                        "from_verdict": prior.value if prior is not None else None,
                        "to_verdict": verdict.verdict.value,
                        "probability": verdict.probability,
                        "crossed_into_apply": crossed,
                    },
                )
                if self._on_transition is not None:
                    self._on_transition(
                        VerdictTransition(
                            ipo_id=verdict.ipo_id,
                            asof=when,
                            from_verdict=prior,
                            to_verdict=verdict.verdict,
                            probability=verdict.probability,
                            crossed_into_apply=crossed,
                        )
                    )
            self._last_verdict[verdict.ipo_id] = verdict.verdict
        self._log_overdue_crossings(when.date())
        _log.info(
            "scheduler_cycle_done",
            extra={
                "scored": len(verdicts),
                "transitions": n_transitions,
                "became_apply": len(became_apply),
            },
        )
        return CycleResult(asof=when, verdicts=verdicts, became_apply=became_apply)

    def _log_overdue_crossings(self, today: date) -> None:
        """Log ``overdue_listing_detected`` (WARN) when an IPO crosses INTO a listing strand.

        finding-④: the console shows the strand live — not only when the operator runs the heartbeat
        ritual. Crossing-only: an IPO that stays overdue is not re-logged every cycle; a mode change
        (``unresolved`` → ``unpriced``) is. Reuses the same prior-state diff as verdict transitions,
        the same mechanism applied twice, not new bespoke state.
        """
        current: dict[str, str] = {}
        for record in self._source.records():
            state = listing_overdue_state(record, today)
            if state is None:
                continue  # on track (open, within the listing window, or fully resolved)
            current[record.ipo_id] = state
            if self._overdue_state.get(record.ipo_id) != state:  # new strand, or a changed mode
                _log.warning(
                    "overdue_listing_detected", extra={"ipo_id": record.ipo_id, "state": state}
                )
        self._overdue_state = current  # drop resolved strands so a later re-strand logs afresh

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
