"""NSE trading-calendar helpers."""

from __future__ import annotations

from datetime import date

import pytest

from ipo.core.calendar import (
    is_trading_day,
    next_trading_day,
    now_ist,
    previous_trading_day,
    trading_days_between,
)
from ipo.core.constants import IST_TZ_NAME


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
