"""State-change alerts (v3 V3-3) — one per edge, repeats suppressed, recovery fires once.

Break on entering/escalating an alerting state; suppress a same-state repeat (count accrues, since
kept); recover once on return to OK. The Oracle 21 and 27 crossings each fire once as the tier
advances. conditions() covers the six op dims + the Oracle tier, never the token.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from ipo.core.constants import IST
from ipo.service.heartbeat import OK, STALE, FeedHealth
from ipo.service.telegram_alerts import (
    AlertCondition,
    ConditionState,
    conditions,
    diff_transitions,
    load_alert_state,
    save_alert_state,
    since_notes,
)
from ipo.service.vm_health import assess_oracle_login, assess_token_expiry
from ipo.service.vm_status import VmStatus

_NOW = datetime(2026, 7, 15, 18, 0, tzinfo=IST)


def _cond(key: str, state: str, detail: str = "x") -> AlertCondition:
    return AlertCondition(key, state, detail)


def test_break_fires_one_alert_then_suppresses_repeats() -> None:
    first, s1 = diff_transitions({}, [_cond("NSE ingest", "broken", "failing")], _NOW)
    assert [t.kind for t in first] == ["break"]  # ONE break on entering the broken state
    assert s1["NSE ingest"].count == 1
    # still broken 30 min later → suppressed; count accrues, since is kept
    later = _NOW + timedelta(minutes=30)
    second, s2 = diff_transitions(s1, [_cond("NSE ingest", "broken", "failing")], later)
    assert second == []
    assert s2["NSE ingest"].count == 2
    assert s2["NSE ingest"].since == s1["NSE ingest"].since


def test_recovery_fires_exactly_one_alert() -> None:
    prev = {"NSE ingest": ConditionState("broken", _NOW, 3)}
    trans, state = diff_transitions(prev, [_cond("NSE ingest", "ok", "recovered")], _NOW)
    assert [t.kind for t in trans] == ["recovered"]
    assert state["NSE ingest"].state == "ok"


def test_oracle_21_and_27_each_fire_exactly_once() -> None:
    key = "Oracle login"
    state: dict[str, ConditionState] = {}
    trans, state = diff_transitions(state, [_cond(key, "ok")], _NOW)  # day 20
    assert trans == []
    trans, state = diff_transitions(state, [_cond(key, "warn")], _NOW)  # day 21: ok -> warn
    assert [t.kind for t in trans] == ["break"]
    trans, state = diff_transitions(state, [_cond(key, "warn")], _NOW)  # day 22-26: suppressed
    assert trans == []
    trans, state = diff_transitions(state, [_cond(key, "urgent")], _NOW)  # day 27: warn -> urgent
    assert [t.kind for t in trans] == ["break"]
    trans, state = diff_transitions(state, [_cond(key, "urgent")], _NOW)  # day 28: suppressed
    assert trans == []


def test_conditions_cover_op_dims_and_oracle_not_token() -> None:
    rows = [FeedHealth("NSE ingest", OK, "ok"), FeedHealth("Read-API", STALE, "down")]
    oracle = assess_oracle_login(date(2026, 7, 13), date(2026, 7, 15))
    token = assess_token_expiry(date(2027, 7, 1), date(2026, 7, 15))
    conds = conditions(VmStatus(_NOW, rows, oracle, token))
    keys = {c.key for c in conds}
    assert {"NSE ingest", "Read-API", "Oracle login"} <= keys
    assert "Upstox token" not in keys  # token is digest-only, never an immediate alert
    assert next(c for c in conds if c.key == "Read-API").alerting


def test_since_notes_only_lists_broken_conditions() -> None:
    state = {
        "Disk": ConditionState("broken", _NOW, 4),
        "NSE ingest": ConditionState("ok", _NOW, 0),
    }
    notes = since_notes(state)
    assert notes == {"Disk": (4, _NOW)}


def test_alert_state_roundtrips(tmp_path: Path) -> None:
    path = tmp_path / "alert_state.json"
    save_alert_state(path, {"Disk": ConditionState("broken", _NOW, 4)})
    loaded = load_alert_state(path)
    assert loaded["Disk"].state == "broken" and loaded["Disk"].count == 4
    assert loaded["Disk"].since == _NOW  # aware datetimes compare by instant


def test_load_alert_state_absent_or_corrupt_is_empty(tmp_path: Path) -> None:
    assert load_alert_state(tmp_path / "nope.json") == {}
    bad = tmp_path / "alert_state.json"
    bad.write_text("{ truncated", encoding="utf-8")
    assert load_alert_state(bad) == {}
