"""Day-wise subscription recorder — bank the buildup curve, forward-only (v2 A1).

The best untested score candidate (subscription *trajectory*, v2 B1) needs the day-by-day
path of how each IPO's book filled — data that is **not reliably archived for free**, so it
exists only if we record it going forward. This is therefore a *clock decision, not a
build-queue decision*: it runs now, decoupled from when trajectory is gated, because every
un-recorded month is history we can never recover (Deep Dive #B).

One pass polls NSE's ``ipo-active-category`` for every **open** mainboard book and appends a
timestamped ``DaywiseSubscriptionRow`` per genuinely-new observation to the append-only bank.
It is a collect-forward *record*, never a scoring input — it does not touch the calibrated
probability (Track A).

Robustness mirrors the live refresh: a whole-fetch failure degrades to zero rows (never
crashes the caller), and a single issue's failure is skipped and logged — a data hiccup must
never take down a scheduled recorder. Schema drift still fails loud inside the parser (there
is no second NSE to corroborate against), surfacing as a logged per-issue error.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ipo.core.calendar import now_ist
from ipo.core.constants import SEGMENT_MAINBOARD
from ipo.core.logging import get_logger
from ipo.core.types import DaywiseSubscriptionRow
from ipo.data.sources.base import SourceError
from ipo.data.sources.nse import NseClient
from ipo.data.store.daywise import DaywiseSubscriptionStore

_log = get_logger("ipo.data.ingest.daywise")


def _multiples(row: DaywiseSubscriptionRow) -> tuple[float | None, ...]:
    return (row.qib_sub, row.nii_sub, row.snii_sub, row.bnii_sub, row.retail_sub, row.total_sub)


def _is_duplicate(candidate: DaywiseSubscriptionRow, latest: DaywiseSubscriptionRow | None) -> bool:
    """True if ``candidate`` repeats the last banked observation (nothing new to record).

    Primary signal is NSE's own ``updateTime`` stamp: same stamp + same multiples ⇒ the same
    published snapshot, so a re-poll within one NSE update cycle banks nothing (this is what
    makes a re-run idempotent). When NSE omits the stamp, fall back to raw-response-hash
    identity. A stamp that has *advanced* is a new publication and is always banked — even if
    the numbers are unchanged — so the trajectory honestly shows demand was flat over that gap.
    """
    if latest is None:
        return False
    if candidate.source_update_time is not None:
        return candidate.source_update_time == latest.source_update_time and _multiples(
            candidate
        ) == _multiples(latest)
    return candidate.raw_response_hash == latest.raw_response_hash


def _has_signal(row: DaywiseSubscriptionRow) -> bool:
    """True if the poll carried anything worth banking (any multiple, or NSE's stamp)."""
    return row.source_update_time is not None or any(m is not None for m in _multiples(row))


def record_daywise_subscription(
    store: DaywiseSubscriptionStore,
    client: NseClient,
    *,
    clock: Callable[[], datetime] = now_ist,
) -> int:
    """Poll open mainboard books once and append new subscription observations. Never raises.

    Returns how many rows were newly banked this pass (0 on an off-day with no open book, or
    when every poll merely repeated the last banked observation).
    """
    try:
        issues = client.current_issues()
    except SourceError as exc:
        _log.warning("daywise_current_issues_failed", extra={"error": str(exc)})
        return 0

    today = clock().date()
    banked = 0
    for issue in issues:
        if issue.segment != SEGMENT_MAINBOARD:
            continue  # SME excluded (Locked decision)
        if issue.open_date is None or issue.close_date is None:
            continue  # can't tell whether the book is open
        if not (issue.open_date <= today <= issue.close_date):
            continue  # only bank while the book is open (close day included — the QIB surge)

        try:
            snapshot = client.subscription_snapshot(issue.symbol)
        except SourceError as exc:
            _log.warning(
                "daywise_snapshot_failed", extra={"symbol": issue.symbol, "error": str(exc)}
            )
            continue

        sub = snapshot.subscription
        row = DaywiseSubscriptionRow(
            ipo_id=issue.symbol.lower(),
            symbol=issue.symbol,
            captured_at=clock(),
            qib_sub=sub.qib,
            nii_sub=sub.nii,
            snii_sub=sub.nii_small,
            bnii_sub=sub.nii_big,
            retail_sub=sub.retail,
            total_sub=sub.total,
            source_update_time=snapshot.source_update_time,
            raw_response_hash=snapshot.raw_hash,
        )
        if not _has_signal(row):
            continue  # empty poll (book not really live yet) — nothing to bank
        if _is_duplicate(row, store.latest_for(row.ipo_id)):
            continue  # NSE hasn't published anything new since the last banked row
        if store.append(row):
            banked += 1

    _log.info("daywise_recorded", extra={"banked": banked})
    return banked
