"""Notification dispatch (Layer 5) — a thin layer over the scheduler's transition signals.

Fires exactly one advisory alert per APPLY *crossing* (``CycleResult.became_apply`` from the
scheduler), so the steady state is never re-alerted — the no-duplicate guarantee is inherited
from step 4's transition tracking. Respects ``NotifyConfig.enabled``. A notification is an
alert, never an action (Inviolable Rule 6).
"""

from __future__ import annotations

from ipo.core.config import AppConfig
from ipo.core.interfaces import Notifier
from ipo.core.types import Verdict
from ipo.service.scheduler import CycleResult


def format_alert(verdict: Verdict) -> str:
    """Build a grounded, advisory alert line for an APPLY crossing."""
    prob = f"{verdict.probability:.0%}" if verdict.probability is not None else "n/a (uncalibrated)"
    return f"IPO {verdict.ipo_id}: {verdict.verdict.value} (P={prob}) — {verdict.reason}"


def notify_crossings(cycle: CycleResult, notifier: Notifier, config: AppConfig) -> list[str]:
    """Alert once per APPLY crossing this cycle; return the alerted ipo_ids.

    No crossings (steady state) → no alerts. ``notify.enabled=False`` → no alerts. The crossing
    set comes from the scheduler, which already de-duplicates, so an IPO that stays APPLY is
    never re-alerted.
    """
    if not config.notify.enabled:
        return []
    by_id = {v.ipo_id: v for v in cycle.verdicts}
    alerted: list[str] = []
    for ipo_id in cycle.became_apply:
        verdict = by_id.get(ipo_id)
        if verdict is None:
            continue
        notifier.notify(verdict, message=format_alert(verdict))
        alerted.append(ipo_id)
    return alerted
