"""Telegram IST display formatters (v3 V3-3) — Indian conventions, cross-platform.

The two single-source helpers render a 12-hour time (AM/PM, no leading zero on the hour) and a
zero-padded DD/MM/YYYY date. Edge cases pinned: midnight -> 12:00 AM, noon -> 12:00 PM. Output is
byte-identical on Windows and the Linux VM, and converts UTC-stored times to IST on the way out.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ipo.core.constants import IST
from ipo.service.telegram_format import _fmt_ist_date, _fmt_ist_time


def _ist(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=IST)


def test_time_pm_has_no_leading_zero_on_hour() -> None:
    assert _fmt_ist_time(_ist(2026, 7, 15, 18, 0)) == "6:00 PM"


def test_time_midnight_is_twelve_am() -> None:
    assert _fmt_ist_time(_ist(2026, 7, 15, 0, 0)) == "12:00 AM"


def test_time_noon_is_twelve_pm() -> None:
    assert _fmt_ist_time(_ist(2026, 7, 15, 12, 0)) == "12:00 PM"


def test_time_minute_is_zero_padded_hour_is_not() -> None:
    assert _fmt_ist_time(_ist(2026, 7, 15, 9, 5)) == "9:05 AM"


def test_date_is_zero_padded_ddmmyyyy() -> None:
    assert _fmt_ist_date(_ist(2026, 7, 1, 10, 0)) == "01/07/2026"
    assert _fmt_ist_date(_ist(2026, 7, 15, 10, 0)) == "15/07/2026"


def test_formatters_convert_utc_to_ist() -> None:
    # 14:00 UTC + 5:30 = 19:30 IST, same date
    utc = datetime(2026, 7, 15, 14, 0, tzinfo=UTC)
    assert _fmt_ist_time(utc) == "7:30 PM"
    assert _fmt_ist_date(utc) == "15/07/2026"
