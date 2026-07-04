"""Structural named constants — defined once, imported everywhere (Ground Rule 2).

These are *structural* facts (timezone, NSE session times, exchange holidays) that
do not change between deployments. Tunable RATES and parameters (sell-cost rates,
weights, thresholds) live in ``config/`` instead — see ``core.config``.
"""

from __future__ import annotations

from datetime import date, time
from zoneinfo import ZoneInfo

# --- Time -------------------------------------------------------------------
# All timestamps in the system are Indian Standard Time (Ground Rule 8).
IST = ZoneInfo("Asia/Kolkata")
IST_TZ_NAME = "Asia/Kolkata"

# NSE equity session (continuous trading), used to reason about the as-of clock.
NSE_SESSION_OPEN = time(9, 15)
NSE_SESSION_CLOSE = time(15, 30)

# --- Segments ---------------------------------------------------------------
SEGMENT_MAINBOARD = "mainboard"
SEGMENT_SME = "sme"

# --- GMP --------------------------------------------------------------------
# Grey-market premium is unofficial and refreshes roughly every half hour during
# active hours (Inviolable Rule 5). Used only to set scrape cadence expectations.
GMP_REFRESH_CADENCE_MINUTES = 30

# --- T+3 settlement cutover -------------------------------------------------
# SEBI shortened the IPO listing timeline from T+6 to T+3 working days: optional
# from 1 Sep 2023, MANDATORY from 1 Dec 2023. The 2021+ backfill straddles this
# structural break, which shortens the ASBA blocked-capital window and may shift
# listing-day behaviour — so it is the natural regime axis for a calibration
# stability check (A4). This is the mandatory-effect date.
# Source: SEBI circular SEBI/HO/CFD/PoD-2/P/CIR/2023/140 (9 Aug 2023).
T3_MANDATORY_CUTOVER: date = date(2023, 12, 1)

# --- NSE trading holidays ---------------------------------------------------
# Maintained list of NSE equity-segment trading holidays. This MUST be reviewed
# annually (NSE publishes the next year's calendar each December). Weekends are
# handled separately in core.calendar; only weekday holidays need to appear here.
#
# Source: NSE trading-holiday circulars. Covers 2024-2026.
NSE_TRADING_HOLIDAYS: frozenset[date] = frozenset(
    {
        # 2024
        date(2024, 1, 26),  # Republic Day
        date(2024, 3, 8),  # Mahashivratri
        date(2024, 3, 25),  # Holi
        date(2024, 3, 29),  # Good Friday
        date(2024, 4, 11),  # Id-Ul-Fitr
        date(2024, 4, 17),  # Ram Navami
        date(2024, 5, 1),  # Maharashtra Day
        date(2024, 6, 17),  # Bakri Id
        date(2024, 7, 17),  # Moharram
        date(2024, 8, 15),  # Independence Day
        date(2024, 10, 2),  # Gandhi Jayanti
        date(2024, 11, 1),  # Diwali Laxmi Pujan (special session aside)
        date(2024, 11, 15),  # Gurunanak Jayanti
        date(2024, 12, 25),  # Christmas
        # 2025
        date(2025, 2, 26),  # Mahashivratri
        date(2025, 3, 14),  # Holi
        date(2025, 3, 31),  # Id-Ul-Fitr
        date(2025, 4, 10),  # Mahavir Jayanti
        date(2025, 4, 14),  # Dr. Ambedkar Jayanti
        date(2025, 4, 18),  # Good Friday
        date(2025, 5, 1),  # Maharashtra Day
        date(2025, 8, 15),  # Independence Day
        date(2025, 8, 27),  # Ganesh Chaturthi
        date(2025, 10, 2),  # Gandhi Jayanti / Dussehra
        date(2025, 10, 21),  # Diwali Laxmi Pujan
        date(2025, 10, 22),  # Diwali Balipratipada
        date(2025, 11, 5),  # Gurunanak Jayanti
        date(2025, 12, 25),  # Christmas
        # 2026 (provisional — confirm against NSE's published 2026 calendar)
        date(2026, 1, 26),  # Republic Day
        date(2026, 3, 17),  # Holi
        date(2026, 4, 3),  # Good Friday
        date(2026, 5, 1),  # Maharashtra Day
        date(2026, 8, 15),  # Independence Day
        date(2026, 10, 2),  # Gandhi Jayanti
        date(2026, 12, 25),  # Christmas
    }
)
