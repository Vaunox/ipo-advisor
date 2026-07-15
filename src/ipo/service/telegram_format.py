"""Render times and dates in Indian conventions for the VM's Telegram messages (v3 V3-3).

The single source of truth for the two display conventions every VM Telegram message uses: a 12-hour
clock with AM/PM and no leading zero on the hour (``6:00 PM``), and a zero-padded ``DD/MM/YYYY``
date (``15/07/2026``). The asymmetry is deliberate — dates padded, hours not — and must not be
"normalised" away. Display only: storage (``oracle_login.json`` ISO) and scheduling (24-hour
``OnCalendar``) keep their own formats; rendering converts on the way out.

The hour is hand-rolled rather than ``strftime("%-I")``: ``%-I`` is a glibc extension that raises on
Windows (where the gate runs) and ``%#I`` is the Windows-only spelling, so the manual form is
byte-identical on both, and hard-coding AM/PM sidesteps ``%p`` locale quirks. ``IST`` is the one
canonical zone from ``ipo.core.constants`` (never redefined here).
"""

from __future__ import annotations

from datetime import datetime

from ipo.core.constants import IST


def _fmt_ist_time(dt: datetime) -> str:
    """Format ``dt`` in IST as a 12-hour clock with AM/PM, no leading zero on the hour.

    Args:
        dt: A timezone-aware datetime (converted to IST before formatting).

    Returns:
        e.g. ``6:00 PM``. Midnight ``00:00`` -> ``12:00 AM``; noon ``12:00`` -> ``12:00 PM``.
    """
    local = dt.astimezone(IST)
    hour12 = local.hour % 12 or 12
    meridiem = "AM" if local.hour < 12 else "PM"
    return f"{hour12}:{local.minute:02d} {meridiem}"


def _fmt_ist_date(dt: datetime) -> str:
    """Format ``dt`` in IST as a zero-padded ``DD/MM/YYYY`` date (e.g. ``15/07/2026``)."""
    return dt.astimezone(IST).strftime("%d/%m/%Y")
