"""Listing-resolution health (v3 finding-④) — catch IPOs the lifecycle strands SILENTLY.

``resolve_listings`` (data/ingest/live.py) completes the Live → History lifecycle by stamping
``listing_date`` (+ the listing price) once NSE reports an issue listed. But it can fail with **no
signal at all**, and then the IPO sits forever wearing an honest-looking "awaiting listing" label:

* **Mode 1 — never resolved.** The book closed, but the symbol never matched in NSE past-issues, so
  ``listing_date`` was never stamped. The row stays "book closed · awaiting listing" indefinitely.
* **Mode 2 — stamped but never priced.** ``listing_date`` is set, yet the bhavcopy price never
  backfilled and the retry window (``PRICE_BACKFILL_DAYS``) has elapsed. The row stays "listed ·
  outcome pending" indefinitely — visible, but it never escalates to an actual outcome.

This module is the ONE definition of "this IPO's listing is overdue", shared by the board badge
(engine.board → the UI's awaiting-listing surface) and the operator heartbeat (run_heartbeat.py), so
the two never drift (the same single-source discipline behind status.ts). It reads only dates the
system already holds — no second data source — so it stays truthful even if Upstox/the context cache
is down. Like the drift monitor (service.monitoring), it fires only past a grace buffer, so a
legitimate one-day listing slip is not mistaken for a strand.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from ipo.core.calendar import next_trading_day
from ipo.core.types import IPORecord
from ipo.data.ingest.live import PRICE_BACKFILL_DAYS

# T+3 is the SEBI norm (book close → listing day, in working days). Beyond it we still allow a small
# trading-day buffer before crying wolf: listings occasionally slip a day, and — like the drift
# monitor's Wilson-interval trigger — the detector should flag a *real* strand, not noise.
LISTING_TRADING_DAYS = 3
OVERDUE_BUFFER_TRADING_DAYS = 2

# Overdue states (None = not overdue). Plain strings so the API/heartbeat can carry the mode.
OVERDUE_UNRESOLVED = "unresolved"  # Mode 1: closed, past expected listing + buffer, no listing_date
OVERDUE_UNPRICED = "unpriced"  # Mode 2: stamped listed, price never backfilled past the window


def _advance_trading_days(day: date, n: int) -> date:
    """The trading day ``n`` NSE sessions after ``day`` (holiday- and weekend-aware)."""
    cursor = day
    for _ in range(n):
        cursor = next_trading_day(cursor)
    return cursor


def listing_overdue_state(record: IPORecord, today: date) -> str | None:
    """Classify an IPO's listing-resolution health as of ``today`` — the strand detector.

    Returns ``OVERDUE_UNRESOLVED`` / ``OVERDUE_UNPRICED`` when the lifecycle should have completed
    but hasn't (a silent strand the operator must inspect), or ``None`` when the IPO is on track
    (book still open, legitimately within the listing/backfill window, or fully resolved).
    """
    if record.close_date >= today:
        return None  # book still open — nothing to resolve yet
    if record.listing_date is None:
        # Mode 1: never resolved. Overdue once we are past the expected listing day + grace buffer.
        expected = _advance_trading_days(
            record.close_date, LISTING_TRADING_DAYS + OVERDUE_BUFFER_TRADING_DAYS
        )
        return OVERDUE_UNRESOLVED if today > expected else None
    if record.listing_open is None:
        # Mode 2: stamped but never priced. Overdue once the bhavcopy retry window has elapsed
        # (resolve_listings stops retrying past it — the price will not arrive on its own now).
        elapsed = (today - record.listing_date).days
        return OVERDUE_UNPRICED if elapsed > PRICE_BACKFILL_DAYS else None
    return None  # fully resolved (date + price) — in History with a real outcome


def is_listing_overdue(record: IPORecord, today: date) -> bool:
    """True when ``record``'s listing resolution is overdue (either strand mode)."""
    return listing_overdue_state(record, today) is not None


def overdue_listings(records: Iterable[IPORecord], today: date) -> list[tuple[str, str]]:
    """Every overdue-listing strand in ``records`` as ``(ipo_id, state)`` — for the heartbeat check.

    A non-empty result is a silent strand the resolution path did not catch; the operator heartbeat
    surfaces it (loudly) so it is caught in the ritual rather than discovered weeks later.
    """
    out: list[tuple[str, str]] = []
    for record in records:
        state = listing_overdue_state(record, today)
        if state is not None:
            out.append((record.ipo_id, state))
    return out
