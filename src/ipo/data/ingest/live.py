"""Live NSE ingestion — turn the running app's static store into a live one (Phase 7 follow-up).

Fetches the exchange's **current/active** IPOs + per-category subscription and upserts them as
``IPORecord``s the engine scores as-of close. This is the runtime ``refresh`` the scheduler was
designed for (``build_service(refresh=...)``) but which shipped unset — the app served frozen demo
data. Only decision-time facts NSE serves officially are used: symbol/dates/price band + QIB/NII/
retail (+ sNII/bNII/overall). Anchor quality, valuation and OFS have no official live feed, so they
stay ``None`` — the engine still scores (``qib_sub`` is the only critical feature), just with less
context, and abstains until the book closes.

Robustness: a network/parse failure of one issue is skipped; a failure of the whole fetch returns 0
and is logged — a live-data hiccup must never crash the sidecar (it degrades to the last store).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from pydantic import ValidationError

from ipo.core.calendar import now_ist
from ipo.core.constants import SEGMENT_MAINBOARD
from ipo.core.interfaces import Repository
from ipo.core.logging import get_logger
from ipo.core.types import IPORecord, Segment
from ipo.data.sources.base import SourceError
from ipo.data.sources.nse import NseClient, NseSubscription

_log = get_logger("ipo.data.ingest.live")


def build_live_records(
    client: NseClient, *, clock: Callable[[], datetime] = now_ist
) -> list[IPORecord]:
    """Fetch current mainboard issues + their subscription and build ``IPORecord``s (pure-ish).

    Raises ``SourceError`` if the current-issues fetch itself fails (the caller decides what to do);
    a per-issue subscription or validation failure is skipped, not fatal. SME issues are excluded.
    """
    issues = client.current_issues()
    records: list[IPORecord] = []
    for issue in issues:
        if issue.segment != SEGMENT_MAINBOARD:
            continue  # SME excluded (Locked decision)
        if issue.price_band_high is None or issue.open_date is None or issue.close_date is None:
            continue  # not enough to build a valid record yet
        try:
            sub = client.subscription(issue.symbol, force=True)
        except SourceError:
            sub = NseSubscription(qib=None, nii=None, retail=None, total=None)
        try:
            records.append(
                IPORecord(
                    ipo_id=issue.symbol.lower(),
                    name=issue.company or issue.symbol,
                    segment=Segment(issue.segment),
                    price_band_low=issue.price_band_low or issue.price_band_high,
                    price_band_high=issue.price_band_high,
                    open_date=issue.open_date,
                    close_date=issue.close_date,
                    qib_sub=sub.qib,
                    nii_sub=sub.nii,
                    retail_sub=sub.retail,
                    nii_small_sub=sub.nii_small,
                    nii_big_sub=sub.nii_big,
                    overall_sub=sub.total,
                    captured_at=clock(),
                )
            )
        except (ValidationError, ValueError) as exc:
            _log.warning("live_record_skipped", extra={"symbol": issue.symbol, "error": str(exc)})
    return records


def refresh_from_nse(
    repo: Repository, client: NseClient, *, clock: Callable[[], datetime] = now_ist
) -> int:
    """Pull live current mainboard IPOs and upsert them; return how many. Never raises.

    A whole-fetch failure (NSE unreachable, cookie/handshake, source drift) is logged and yields 0 —
    the app keeps serving the last known store rather than going dark.
    """
    try:
        records = build_live_records(client, clock=clock)
    except SourceError as exc:
        _log.warning("live_refresh_failed", extra={"error": str(exc)})
        return 0
    if records:
        repo.upsert_many(records)
    _log.info("live_refresh_done", extra={"records": len(records)})
    return len(records)
