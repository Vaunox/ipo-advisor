"""Telegram render layer (v3 V3-3) — Indian date/time conventions + the digest/status/alert output.

The IST helpers render a 12-hour time (AM/PM, no leading zero on the hour) and a zero-padded
DD/MM/YYYY date, byte-identical on the Windows gate and the Linux VM. The digest/status render the
same VmStatus (so /status == digest), with the never-recorded Oracle line, the headline OK/DEGRADED
flip, and the suppression note; format_alert renders one break/recovered line.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from ipo.core.constants import IST
from ipo.service.heartbeat import OK, STALE, FeedHealth
from ipo.service.telegram_alerts import Transition
from ipo.service.telegram_format import (
    _fmt_ist_date,
    _fmt_ist_time,
    format_alert,
    format_digest,
    format_status,
)
from ipo.service.vm_health import assess_oracle_login, assess_token_expiry
from ipo.service.vm_status import VmStatus

_NOW = datetime(2026, 7, 15, 18, 0, tzinfo=IST)
_TODAY = date(2026, 7, 15)


def _ist(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=IST)


# --- the two IST helpers (single source of truth) ----------------------------------------------


def test_time_pm_has_no_leading_zero_on_hour() -> None:
    assert _fmt_ist_time(_ist(2026, 7, 15, 18, 0)) == "6:00 PM"


def test_time_midnight_is_twelve_am() -> None:
    assert _fmt_ist_time(_ist(2026, 7, 15, 0, 0)) == "12:00 AM"


def test_time_noon_is_twelve_pm() -> None:
    assert _fmt_ist_time(_ist(2026, 7, 15, 12, 0)) == "12:00 PM"


def test_time_minute_is_zero_padded_hour_is_not() -> None:
    assert _fmt_ist_time(_ist(2026, 7, 15, 9, 5)) == "9:05 AM"


def test_date_zero_padded_for_both_datetime_and_plain_date() -> None:
    assert _fmt_ist_date(_ist(2026, 7, 1, 10, 0)) == "01/07/2026"
    assert _fmt_ist_date(date(2027, 7, 1)) == "01/07/2027"  # plain date (token expiry) formats too


def test_formatters_convert_utc_to_ist() -> None:
    utc = datetime(2026, 7, 15, 14, 0, tzinfo=UTC)  # 14:00 UTC + 5:30 = 19:30 IST, same date
    assert _fmt_ist_time(utc) == "7:30 PM"
    assert _fmt_ist_date(utc) == "15/07/2026"


# --- the digest / status / alert renderers -----------------------------------------------------


def _ok_rows() -> list[FeedHealth]:
    return [
        FeedHealth("NSE ingest", OK, "last good pull 22m ago"),
        FeedHealth("Upstox ctx", OK, "refreshed 3h ago"),
        FeedHealth("Read-API", OK, "up"),
        FeedHealth("Disk", OK, "78% free"),
        FeedHealth("Keepalive", OK, "keepalive 14m ago"),
        FeedHealth("Commands", OK, "listening"),
    ]


def _status(rows: list[FeedHealth], login: date | None) -> VmStatus:
    oracle = assess_oracle_login(login, _TODAY)
    token = assess_token_expiry(date(2027, 7, 1), _TODAY)
    return VmStatus(_NOW, rows, oracle, token)


def test_digest_headline_ok_uses_indian_datetime() -> None:
    out = format_digest(_status(_ok_rows(), _TODAY - timedelta(days=2)))
    assert "IPO VM — OK" in out and "🟢" in out
    assert "Wed 15/07/2026, 6:00 PM IST" in out  # weekday + DD/MM/YYYY + 12-hour
    assert "01/07/2027 · 351 days left" in out  # token line (DD/MM/YYYY)
    assert "13/07/2026 · 2 days ago" in out  # Oracle date in DD/MM/YYYY


def test_digest_degraded_when_a_dim_is_down() -> None:
    rows = _ok_rows()
    rows[2] = FeedHealth("Read-API", STALE, "not responding on :8000")
    out = format_digest(_status(rows, _TODAY - timedelta(days=2)))
    assert "IPO VM — DEGRADED" in out and "🔴" in out
    assert "✗ Read-API" in out


def test_digest_never_recorded_oracle_line_and_degrades() -> None:
    out = format_digest(_status(_ok_rows(), None))  # never recorded
    assert "⚠️ none recorded — run /login to start the 30-day countdown" in out
    assert "IPO VM — DEGRADED" in out  # a missing login flips DEGRADED


def test_digest_warn_oracle_shows_date_and_does_not_degrade() -> None:
    out = format_digest(_status(_ok_rows(), _TODAY - timedelta(days=21)))
    assert "⚠️ 24/06/2026 · 21 days ago — log in soon" in out
    assert "IPO VM — OK" in out  # warn(21) shows its line but the headline stays OK


def test_digest_suppression_note_uses_12_hour_time() -> None:
    rows = _ok_rows()
    rows[0] = FeedHealth("NSE ingest", STALE, "NSE fetch failing — last good pull 4h ago")
    since = {"NSE ingest": (6, datetime(2026, 7, 15, 14, 0, tzinfo=IST))}
    out = format_digest(_status(rows, _TODAY - timedelta(days=2)), since_by_key=since)
    assert "6 consecutive since 2:00 PM" in out


def test_status_is_identical_to_the_digest() -> None:
    status = _status(_ok_rows(), _TODAY - timedelta(days=2))
    assert format_status(status) == format_digest(status)


def test_format_alert_break_and_recovered() -> None:
    brk = format_alert(
        Transition("NSE ingest", "break", "NSE fetch failing — last good pull 4h ago")
    )
    assert brk == "⚠️ NSE ingest — NSE fetch failing — last good pull 4h ago"
    assert format_alert(Transition("Read-API", "recovered", "up")) == "✅ Read-API recovered — up"


def test_never_recorded_string_adapts_per_surface() -> None:
    # one canonical detail; the digest uses the "Oracle login" column (no inner label), the alert
    # (which has no column) prepends "Oracle login —" via format_alert
    oracle = assess_oracle_login(None, _TODAY)
    alert = format_alert(Transition("Oracle login", "break", oracle.feed.detail))
    assert alert == "⚠️ Oracle login — none recorded — run /login to start the 30-day countdown"
    assert "⚠️ none recorded — run /login" in format_digest(_status(_ok_rows(), None))
