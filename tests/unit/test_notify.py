"""Phase 6 step 5: advisory notifications fire once per APPLY crossing, respecting config.

* One alert per crossing INTO APPLY; the steady state (no crossing) is never re-alerted.
* ``notify.enabled=False`` → silent. Channel selects the sink (none/log/push); telegram/email
  are deferred and raise rather than silently drop.
* A notification is an alert, never an action.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from ipo.core.config import AppConfig, load_config
from ipo.core.constants import IST
from ipo.core.types import Verdict, VerdictType
from ipo.service.notify import (
    LogNotifier,
    NullNotifier,
    PushNotifier,
    build_notifier,
    notify_crossings,
)
from ipo.service.scheduler import CycleResult


class _Collector:
    """A Notifier that records what it was asked to send."""

    def __init__(self) -> None:
        self.alerts: list[tuple[str, str]] = []

    def notify(self, verdict: Verdict, *, message: str) -> None:
        self.alerts.append((verdict.ipo_id, message))


def _cycle(became_apply: list[str], verdicts: list[Verdict]) -> CycleResult:
    return CycleResult(
        asof=datetime(2026, 6, 30, tzinfo=IST), verdicts=verdicts, became_apply=became_apply
    )


def _enabled() -> AppConfig:
    return load_config(env="dev", environ={}, overrides={"notify": {"enabled": True}})


def test_alerts_once_per_apply_crossing() -> None:
    config = _enabled()
    collector = _Collector()
    apply = Verdict(ipo_id="X", verdict=VerdictType.APPLY, probability=0.82, reason="QIB 200x")

    # Crossing cycle: X just became APPLY -> one alert.
    sent = notify_crossings(_cycle(["X"], [apply]), collector, config)
    assert sent == ["X"]
    assert len(collector.alerts) == 1
    assert collector.alerts[0][0] == "X" and "APPLY" in collector.alerts[0][1]

    # Steady state: X stays APPLY but did not cross this cycle -> no re-alert.
    sent2 = notify_crossings(_cycle([], [apply]), collector, config)
    assert sent2 == []
    assert len(collector.alerts) == 1  # still one — never re-alerted


def test_respects_enabled_flag() -> None:
    disabled = load_config(env="dev", environ={})  # notify.enabled defaults False
    collector = _Collector()
    apply = Verdict(ipo_id="X", verdict=VerdictType.APPLY, probability=0.8)
    assert notify_crossings(_cycle(["X"], [apply]), collector, disabled) == []
    assert collector.alerts == []


def test_build_notifier_by_channel() -> None:
    none_cfg = load_config(env="dev", environ={})  # default channel "none"
    assert isinstance(build_notifier(none_cfg), NullNotifier)

    log_cfg = load_config(env="dev", environ={}, overrides={"notify": {"channel": "log"}})
    assert isinstance(build_notifier(log_cfg), LogNotifier)

    push_cfg = load_config(env="dev", environ={}, overrides={"notify": {"channel": "push"}})
    sent: list[str] = []
    notifier = build_notifier(push_cfg, push_transport=sent.append)
    assert isinstance(notifier, PushNotifier)
    notifier.notify(Verdict(ipo_id="X", verdict=VerdictType.APPLY, probability=0.8), message="hi")
    assert sent == ["hi"]

    telegram_cfg = load_config(env="dev", environ={}, overrides={"notify": {"channel": "telegram"}})
    with pytest.raises(NotImplementedError):
        build_notifier(telegram_cfg)


def test_null_notifier_is_noop() -> None:
    # No sink, no error — channel "none" is a deliberate silent drop.
    NullNotifier().notify(Verdict(ipo_id="X", verdict=VerdictType.APPLY), message="x")
