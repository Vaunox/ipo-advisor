"""Render the VM's Telegram messages in Indian conventions (v3 V3-3).

The single source of truth for the two display conventions every message uses: a 12-hour clock with
AM/PM and **no leading zero on the hour** (``6:00 PM``), and a **zero-padded ``DD/MM/YYYY``** date
(``15/07/2026``). The asymmetry is deliberate — dates padded, hours not — never "normalised"
away. Display only: storage (``oracle_login.json`` ISO) and scheduling (24-hour ``OnCalendar``) keep
their own formats; rendering converts on the way out.

The hour is hand-rolled rather than ``strftime("%-I")``: ``%-I`` is a glibc extension that raises on
Windows (the gate) and ``%#I`` is the Windows-only spelling, so the manual form is byte-identical on
both, and hard-coding AM/PM sidesteps ``%p`` locale quirks. ``IST`` is the one canonical zone from
``ipo.core.constants`` (never redefined here).

``format_digest`` and ``format_status`` render the same ``VmStatus`` snapshot, so /status returns
byte-identical output to the digest; ``format_alert`` renders one transition line.
"""

from __future__ import annotations

import html
from collections.abc import Mapping
from datetime import date, datetime

from ipo.core.constants import IST
from ipo.service.heartbeat import FeedHealth
from ipo.service.telegram_alerts import Transition
from ipo.service.vm_health import OracleLoginHealth
from ipo.service.vm_status import VmStatus

_NAME_WIDTH = 12
_LABEL_WIDTH = 14


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


def _fmt_ist_date(dt: date | datetime) -> str:
    """Format a date/datetime as zero-padded ``DD/MM/YYYY`` (e.g. ``15/07/2026``).

    A datetime is converted to IST first; a plain ``date`` (login/expiry dates, which carry no time)
    is formatted directly. Both yield the same DD/MM/YYYY convention — one date formatter, no forks.
    """
    if isinstance(dt, datetime):
        dt = dt.astimezone(IST)
    return dt.strftime("%d/%m/%Y")


def _fmt_headline_when(dt: datetime) -> str:
    """Headline stamp: weekday + DD/MM/YYYY + 12-hour IST, e.g. ``Wed 15/07/2026, 6:00 PM``."""
    return f"{dt.astimezone(IST).strftime('%a')} {_fmt_ist_date(dt)}, {_fmt_ist_time(dt)} IST"


def _oracle_text(oracle: OracleLoginHealth) -> str:
    """The Oracle-login value: login date + countdown detail, with ⚠️ for warn/urgent/none."""
    if oracle.tier == "none" or oracle.last_login is None:
        return f"⚠️ {oracle.feed.detail}"  # e.g. the never-recorded prompt
    prefix = "⚠️ " if oracle.tier in ("warn", "urgent") else ""
    return f"{prefix}{_fmt_ist_date(oracle.last_login)} · {oracle.feed.detail}"


def _row_line(row: FeedHealth, note: str) -> str:
    """One operational row: ``✓/✗ <name>  <detail>`` plus an optional suppression note."""
    line = f"{'✓' if row.ok else '✗'} {row.name.ljust(_NAME_WIDTH)} {row.detail}"
    return f"{line} · {note}" if note else line


def format_digest(
    status: VmStatus, *, since_by_key: Mapping[str, tuple[int, datetime]] | None = None
) -> str:
    """Render the twice-daily digest / ``/status`` snapshot (HTML, aligned monospace body).

    ``since_by_key`` annotates a still-broken row with ``N consecutive since HH:MM`` (from the alert
    state), so an ongoing failure shows its count + start time; healthy rows carry no note.
    """
    since_by_key = since_by_key or {}
    rows = []
    for row in status.rows:
        note = ""
        if not row.ok and row.name in since_by_key:
            count, since = since_by_key[row.name]
            note = f"{count} consecutive since {_fmt_ist_time(since)}"
        rows.append(_row_line(row, note))
    token = status.token
    tok = f"{_fmt_ist_date(token.expiry)} · {token.days_left} days left"
    token_line = f"{'Upstox token'.ljust(_LABEL_WIDTH)} {tok}"
    oracle_line = f"{'Oracle login'.ljust(_LABEL_WIDTH)} {_oracle_text(status.oracle)}"
    body = "\n".join(rows) + "\n" + ("─" * 13) + "\n" + token_line + "\n" + oracle_line
    dot = "🟢" if not status.degraded else "🔴"
    header = f"{dot} <b>IPO VM — {status.headline}</b> · {_fmt_headline_when(status.computed_at)}"
    return f"{header}\n<pre>{html.escape(body)}</pre>"


def format_status(
    status: VmStatus, *, since_by_key: Mapping[str, tuple[int, datetime]] | None = None
) -> str:
    """Render the ``/status`` reply — identical to the digest (same snapshot, same fields)."""
    return format_digest(status, since_by_key=since_by_key)


def format_alert(transition: Transition) -> str:
    """Render one immediate-alert line: a breaking ``⚠️`` or a ``✅ recovered`` message."""
    if transition.kind == "recovered":
        return f"✅ {transition.key} recovered — {transition.detail}"
    return f"⚠️ {transition.key} — {transition.detail}"


def format_login_confirmation(recorded: date) -> str:
    """The ``/login`` reply confirming the recorded Oracle sign-in date (DD/MM/YYYY)."""
    return f"✅ Recorded Oracle sign-in {_fmt_ist_date(recorded)} — 30-day countdown reset."
