"""NSE trading-calendar helpers."""

from __future__ import annotations

from datetime import date

import pytest

from ipo.core.calendar import (
    is_trading_day,
    latest_covered_year,
    next_trading_day,
    now_ist,
    previous_trading_day,
    review_due,
    trading_days_between,
)
from ipo.core.constants import IST_TZ_NAME, NSE_TRADING_HOLIDAYS


def test_now_ist_is_timezone_aware() -> None:
    now = now_ist()
    assert now.tzinfo is not None
    assert str(now.tzinfo) == IST_TZ_NAME


def test_weekend_is_not_trading() -> None:
    assert is_trading_day(date(2026, 1, 3)) is False  # Saturday
    assert is_trading_day(date(2026, 1, 4)) is False  # Sunday


def test_known_holiday_is_not_trading() -> None:
    assert is_trading_day(date(2026, 1, 26)) is False  # Republic Day


def test_ordinary_weekday_is_trading() -> None:
    assert is_trading_day(date(2026, 1, 5)) is True  # Monday, not a holiday


def test_next_trading_day_skips_weekend() -> None:
    # Friday -> Monday (Jan 2 2026 is a Friday).
    assert next_trading_day(date(2026, 1, 2)) == date(2026, 1, 5)


def test_next_trading_day_skips_holiday() -> None:
    # Jan 26 2026 (Mon) is Republic Day -> next is Jan 27 (Tue).
    assert next_trading_day(date(2026, 1, 23)) == date(2026, 1, 27)


def test_previous_trading_day_skips_weekend() -> None:
    assert previous_trading_day(date(2026, 1, 5)) == date(2026, 1, 2)


def test_trading_days_between_excludes_weekend_and_holiday() -> None:
    days = trading_days_between(date(2026, 1, 23), date(2026, 1, 27))
    # Fri 23, [Sat 24, Sun 25 weekend], [Mon 26 holiday], Tue 27.
    assert days == [date(2026, 1, 23), date(2026, 1, 27)]


def test_trading_days_between_rejects_reversed_range() -> None:
    with pytest.raises(ValueError):
        trading_days_between(date(2026, 1, 5), date(2026, 1, 1))


def test_holi_2026_is_the_authoritative_date() -> None:
    # Regression: the provisional set had Holi on 2026-03-17 (a lunar guess); the NSE
    # circular puts it on 2026-03-03. Lock the corrected date in both directions.
    assert is_trading_day(date(2026, 3, 3)) is False  # Holi (corrected)
    assert is_trading_day(date(2026, 3, 17)) is True  # ordinary Tuesday now


def test_current_year_calendar_is_plausibly_complete() -> None:
    # Guard against a truncated/empty year slipping in: NSE has ~14-16 weekday holidays.
    latest = latest_covered_year()
    count = sum(1 for d in NSE_TRADING_HOLIDAYS if d.year == latest)
    assert count >= 12, f"holiday set for {latest} looks thin ({count}) — review the NSE circular"


def test_review_due_tracks_the_calendar_horizon() -> None:
    latest = latest_covered_year()
    assert review_due(date(latest, 6, 1)) is True  # in the last covered year -> due
    assert review_due(date(latest - 1, 6, 1)) is False  # still a year of runway
    assert review_due(date(latest + 1, 1, 1)) is True  # past the horizon -> overdue
