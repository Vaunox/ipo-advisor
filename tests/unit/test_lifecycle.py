"""Listing-resolution strand detector (v3 finding-④) — the overdue classifier.

Proves the ONE definition of "this IPO's listing is overdue" (service.lifecycle) catches BOTH
silent-strand modes, respects a holiday-aware grace buffer (so a legit slip is not a false alarm),
and stays quiet for on-track IPOs. Offline + deterministic (fixed clock, real NSE 2026 calendar).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from ipo.core.types import IPORecord, Segment
from ipo.data.ingest.live import PRICE_BACKFILL_DAYS
from ipo.data.store.repository import ParquetRepository
from ipo.service.lifecycle import (
    OVERDUE_UNPRICED,
    OVERDUE_UNRESOLVED,
    is_listing_overdue,
    listing_overdue_state,
    overdue_listings,
)


def _rec(
    ipo_id: str,
    *,
    close: date,
    listing: date | None = None,
    listing_open: float | None = None,
) -> IPORecord:
    return IPORecord(
        ipo_id=ipo_id,
        name=ipo_id.upper(),
        segment=Segment("mainboard"),
        price_band_low=100.0,
        price_band_high=110.0,
        open_date=close.replace(day=1),
        close_date=close,
        listing_date=listing,
        listing_open=listing_open,
        qib_sub=3.0,
        captured_at=datetime(2026, 7, 3, 17, 0),
    )


# Close Mon 2026-07-06. Trading days after: Tue7 Wed8 Thu9(T+3) Fri10 Mon13(+buffer); 07-11/12
# weekend skipped. So a Mode-1 strand fires only once today > 2026-07-13.
_CLOSE = date(2026, 7, 6)


def test_open_book_is_never_overdue() -> None:
    assert listing_overdue_state(_rec("a", close=date(2026, 7, 20)), date(2026, 7, 14)) is None


def test_within_listing_window_is_not_overdue() -> None:
    # Closed, but only T+4 has passed — still inside the expected-listing + buffer window.
    assert listing_overdue_state(_rec("a", close=_CLOSE), date(2026, 7, 10)) is None


def test_at_expected_plus_buffer_is_not_yet_overdue() -> None:
    # Exactly the expected+buffer trading day (2026-07-13) — strict '>' means not yet a strand.
    assert listing_overdue_state(_rec("a", close=_CLOSE), date(2026, 7, 13)) is None


def test_mode1_unresolved_strand_past_buffer() -> None:
    # Past expected+buffer with no listing_date ever stamped → symbol never matched → strand.
    st = listing_overdue_state(_rec("a", close=_CLOSE), date(2026, 7, 14))
    assert st == OVERDUE_UNRESOLVED
    assert is_listing_overdue(_rec("a", close=_CLOSE), date(2026, 7, 14)) is True


def test_buffer_is_holiday_and_weekend_aware() -> None:
    # Close Thu 2026-09-10. 09-12/13 weekend + 09-14 Ganesh Chaturthi (NSE holiday) all skipped, so
    # expected+buffer is the 5th TRADING day = 2026-09-18. A naive +5 calendar days would be 09-15
    # and would falsely flag 09-16. Holiday-aware counting keeps it quiet.
    rec = _rec("a", close=date(2026, 9, 10))
    assert listing_overdue_state(rec, date(2026, 9, 16)) is None  # naive-calendar would cry wolf
    assert listing_overdue_state(rec, date(2026, 9, 21)) == OVERDUE_UNRESOLVED  # genuinely past it


def test_fully_resolved_is_not_overdue() -> None:
    rec = _rec("a", close=_CLOSE, listing=date(2026, 7, 9), listing_open=125.0)
    assert listing_overdue_state(rec, date(2026, 8, 1)) is None


def test_mode2_price_pending_within_window_is_not_overdue() -> None:
    # Stamped listed, price still backfilling but inside the retry window → on track, not a strand.
    listing = date(2026, 7, 9)
    within = date(2026, 7, 9 + PRICE_BACKFILL_DAYS)  # exactly the last retry day
    rec = _rec("a", close=_CLOSE, listing=listing, listing_open=None)
    assert listing_overdue_state(rec, within) is None


def test_mode2_unpriced_strand_past_backfill_window() -> None:
    # Stamped listed, but the price never backfilled and the retry window has elapsed → strand.
    listing = date(2026, 7, 9)
    past = date(2026, 7, 10 + PRICE_BACKFILL_DAYS)  # one day past the window
    rec = _rec("a", close=_CLOSE, listing=listing, listing_open=None)
    assert listing_overdue_state(rec, past) == OVERDUE_UNPRICED


def test_overdue_listings_collects_both_modes_and_skips_healthy() -> None:
    today = date(2026, 7, 30)
    healthy = _rec("ok", close=_CLOSE, listing=date(2026, 7, 9), listing_open=120.0)
    mode1 = _rec("m1", close=_CLOSE)  # never stamped
    mode2 = _rec("m2", close=_CLOSE, listing=date(2026, 7, 9), listing_open=None)  # never priced
    result = dict(overdue_listings([healthy, mode1, mode2], today))
    assert result == {"m1": OVERDUE_UNRESOLVED, "m2": OVERDUE_UNPRICED}


def test_overdue_listings_over_a_real_parquet_store(tmp_path: Path) -> None:
    """The heartbeat path: strands read straight off a real ParquetRepository (production shape)."""
    repo = ParquetRepository(tmp_path)
    repo.upsert(_rec("strand", close=_CLOSE))  # never resolved
    repo.upsert(_rec("ok", close=_CLOSE, listing=date(2026, 7, 9), listing_open=120.0))
    assert dict(overdue_listings(repo.list_all(), date(2026, 7, 30))) == {
        "strand": OVERDUE_UNRESOLVED
    }
