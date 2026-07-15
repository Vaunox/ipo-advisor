"""State-change alert engine for the Telegram surface (v3 V3-3) — one alert per edge, no cry-wolf.

Compares the current health conditions (from a ``VmStatus`` snapshot) against the persisted
``alert_state.json`` and emits transitions: ONE "break" when a condition first enters an alerting
state (or escalates to a worse one, e.g. the Oracle 21->27 step), ONE "recovered" when it clears,
and nothing while it stays broken — the repeat is suppressed while count + since accrue for the
digest's "N consecutive since HH:MM" note.

Single writer: only the alert-check timer writes ``alert_state.json``; the digest only reads it.
Rendering of the transition text lives in ``telegram_format`` (this module stays pure logic).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ipo.service.vm_status import VmStatus

_OK = "ok"


@dataclass(frozen=True)
class ConditionState:
    """A condition's persisted state: its label, when it entered that label, and checks-since."""

    state: str
    since: datetime
    count: int


@dataclass(frozen=True)
class AlertCondition:
    """A condition's CURRENT reading from a snapshot: an alert key, its state label, and detail."""

    key: str
    state: str  # "ok" when healthy; "broken" / an Oracle tier when alerting
    detail: str

    @property
    def alerting(self) -> bool:
        """True when the condition is in a non-OK (alert-worthy) state."""
        return self.state != _OK


@dataclass(frozen=True)
class Transition:
    """An emitted edge: a condition ``key`` broke or recovered, carrying the health ``detail``."""

    key: str
    kind: str  # "break" | "recovered"
    detail: str


def conditions(status: VmStatus) -> list[AlertCondition]:
    """Extract the alert conditions from a snapshot: the six operational dims + the Oracle tier.

    Token expiry is intentionally NOT an alert condition — it is a slow annual countdown in the
    digest; an expired token surfaces as a context/ingest failure, which alerts on its own.
    """
    conds = [
        AlertCondition(row.name, _OK if row.ok else "broken", row.detail) for row in status.rows
    ]
    conds.append(AlertCondition("Oracle login", status.oracle.tier, status.oracle.feed.detail))
    return conds


def diff_transitions(
    prev: dict[str, ConditionState], current: list[AlertCondition], now: datetime
) -> tuple[list[Transition], dict[str, ConditionState]]:
    """Diff current conditions against the persisted state; return ``(transitions, new_state)``.

    Break on entering or escalating to an alerting state (a state-label change while alerting);
    suppress a same-state repeat (count++, since kept); recover on returning to OK. ``new_state`` is
    what the caller persists — the alert-check timer is the only writer of ``alert_state.json``.
    """
    transitions: list[Transition] = []
    new_state: dict[str, ConditionState] = {}
    for cond in current:
        prior = prev.get(cond.key)
        if cond.alerting:
            if prior is None or prior.state == _OK or prior.state != cond.state:
                # newly broken, or escalated to a different alerting state (Oracle warn -> urgent)
                transitions.append(Transition(cond.key, "break", cond.detail))
                new_state[cond.key] = ConditionState(cond.state, now, 1)
            else:
                # same alerting state: suppress; accrue the count and keep the original since
                new_state[cond.key] = ConditionState(prior.state, prior.since, prior.count + 1)
        else:
            if prior is not None and prior.state != _OK:
                transitions.append(Transition(cond.key, "recovered", cond.detail))
            new_state[cond.key] = ConditionState(_OK, now, 0)
    return transitions, new_state


def since_notes(state: dict[str, ConditionState]) -> dict[str, tuple[int, datetime]]:
    """Map each still-broken condition to ``(count, since)`` for the digest's suppression note."""
    return {key: (cs.count, cs.since) for key, cs in state.items() if cs.state != _OK}


def load_alert_state(path: Path) -> dict[str, ConditionState]:
    """Load the persisted alert state (``{}`` if absent/corrupt — a fresh start, never an error)."""
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    state: dict[str, ConditionState] = {}
    for key, val in raw.items():
        try:
            state[str(key)] = ConditionState(
                str(val["state"]), datetime.fromisoformat(str(val["since"])), int(val["count"])
            )
        except (KeyError, TypeError, ValueError):
            continue
    return state


def save_alert_state(path: Path, state: dict[str, ConditionState]) -> None:
    """Persist the alert state atomically (single writer: the alert-check timer)."""
    payload = {
        key: {"state": cs.state, "since": cs.since.isoformat(), "count": cs.count}
        for key, cs in state.items()
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
