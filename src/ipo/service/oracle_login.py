"""Persistent record of the operator's last Oracle-console sign-in (v3 V3-3).

The bot's ``/login`` command writes today's date here; the digest, ``/status``, and the alert-check
read it to drive the 30-day reclaim countdown and the 21/27-day warnings — an honest self-report
— the bot records that the operator SAID they signed in; it cannot verify against Oracle (that would
need Oracle credentials on the box, which we refuse). Stored as ISO so it stays machine-parseable;
rendering converts to DD/MM/YYYY on the way out.

Single writer: only the bot daemon (on an authorised ``/login``) writes it; every other reader
is read-only. A missing or corrupt file is a clean "no login on record" (``None``), never an error —
the countdown treats absence as a first-class, DEGRADED-flipping state.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from ipo.core.calendar import now_ist


def read_oracle_login(path: Path) -> date | None:
    """Return the recorded last sign-in date, or ``None`` if never recorded / unreadable (sentinel).

    Never raises: an absent file, malformed JSON, or a bad date all read as ``None`` — a missing
    record is the honest "no login on record" state, handled first-class by the countdown.
    """
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        return date.fromisoformat(str(raw["last_login"]))
    except (ValueError, KeyError, TypeError, OSError):
        return None


def record_oracle_login(path: Path, *, now: datetime | None = None) -> date:
    """Record 'the operator signed in today' (IST): ISO ``last_login`` + full ISO ``recorded_at``.

    Returns the recorded date. Single-writer: only the bot daemon calls this, on an authorised
    ``/login`` — the only write in the whole Telegram path. Written atomically (temp + replace).
    """
    stamp = now or now_ist()
    today = stamp.date()
    payload = {"last_login": today.isoformat(), "recorded_at": stamp.isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
    return today
