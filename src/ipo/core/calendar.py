"""NSE trading calendar and IST clock (Ground Rule 8 / Inviolable Rule 2).

A trading day is a weekday that is not an NSE equity-segment holiday. These helpers
let the as-of clock reason about when a book closes and when an issue is expected
to list. The holiday set is maintained in ``core.constants``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from ipo.core.constants import IST, NSE_TRADING_HOLIDAYS

# Saturday=5, Sunday=6 in date.weekday().
_WEEKEND = frozenset({5, 6})


def now_ist() -> datetime:
    """Return the current time in IST (the system's canonical timezone)."""
    return datetime.now(tz=IST)


def is_trading_day(day: date) -> bool:
    """True if ``day`` is an NSE equity trading day (weekday and not a holiday)."""
    return day.weekday() not in _WEEKEND and day not in NSE_TRADING_HOLIDAYS


def next_trading_day(day: date) -> date:
    """Return the first trading day strictly after ``day``."""
    cursor = day + timedelta(days=1)
    while not is_trading_day(cursor):
        cursor += timedelta(days=1)
    return cursor


def previous_trading_day(day: date) -> date:
    """Return the last trading day strictly before ``day``."""
    cursor = day - timedelta(days=1)
    while not is_trading_day(cursor):
        cursor -= timedelta(days=1)
    return cursor


def trading_days_between(start: date, end: date) -> list[date]:
    """Return the trading days in the inclusive range ``[start, end]``.

    Raises:
        ValueError: if ``end`` precedes ``start``.
    """
    if end < start:
        raise ValueError("end must be on or after start")
    days: list[date] = []
    cursor = start
    while cursor <= end:
        if is_trading_day(cursor):
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def latest_covered_year() -> int:
    """Return the last calendar year the holiday set covers.

    The holiday set MUST be reviewed each December when NSE publishes the next year's
    calendar (see ``core.constants``). Exposing the horizon lets an operator check flag a
    stale calendar before it silently treats an un-loaded holiday as a trading day.
    """
    return max(day.year for day in NSE_TRADING_HOLIDAYS)


def review_due(today: date | None = None) -> bool:
    """True when the holiday calendar should be extended with the next year's NSE circular.

    Becomes due once the current date reaches the last covered year: by then NSE has
    published (or is about to publish) the following year's holidays, and the tail of the
    calendar is one bad assumption away from treating a real holiday as a trading day.
    """
    ref = today or now_ist().date()
    return ref.year >= latest_covered_year()
