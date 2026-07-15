"""Assemble the VM health snapshot for the Telegram surface (v3 V3-3) — a PURE read.

``build_status`` gathers the live facts (ingest state, disk, keepalive + bot markers, context
freshness, a real read-API probe, the Oracle-login record, the token expiry) and runs the shared
``vm_health`` judges over them into one ``VmStatus``. It is side-effect-free: ``/status`` and the
twice-daily digest both render from a ``VmStatus``, so they are byte-identical by construction — the
only writer in the Telegram path is ``/login`` (``oracle_login.record_oracle_login``), never here.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import requests

from ipo.core.constants import IST
from ipo.data.ingest.state import IngestStateStore
from ipo.service.heartbeat import FeedHealth
from ipo.service.oracle_login import read_oracle_login
from ipo.service.vm_health import (
    VM_INGEST_MAX_AGE,
    VM_KEEPALIVE_MAX_AGE,
    OracleLoginHealth,
    TokenExpiry,
    assess_oracle_login,
    assess_token_expiry,
    check_bot_listener,
    check_context,
    check_disk,
    check_ingest,
    check_keepalive,
    check_read_api,
)

# The Upstox token is a fixed one-year read-only Analytics Token (V3-1 deploy): expires 01/07/2027.
UPSTOX_TOKEN_EXPIRY = date(2027, 7, 1)

_KEEPALIVE_MARKER = "keepalive.marker"
_BOT_MARKER = "bot.marker"
_CONTEXT_FILE = Path("context") / "ipo_context.json"
_ORACLE_LOGIN_FILE = "oracle_login.json"
_READ_API_BASE = "http://127.0.0.1:8000"


@dataclass(frozen=True)
class VmStatus:
    """A point-in-time VM health snapshot — a pure read; /status and digest render identically.

    ``rows`` are the operational dims (NSE ingest, context, read-API, disk, keepalive, commands)
    that drive DEGRADED; ``oracle`` and ``token`` are the countdown dimensions rendered on their own
    lines. ``degraded`` also folds in the Oracle 'none'/'urgent' tiers and an expired token.
    """

    computed_at: datetime
    rows: list[FeedHealth]
    oracle: OracleLoginHealth
    token: TokenExpiry

    @property
    def degraded(self) -> bool:
        """DEGRADED if any operational dim is not OK, login missing/urgent, or token expired."""
        if any(not r.ok for r in self.rows):
            return True
        if self.oracle.tier in ("none", "urgent"):
            return True
        return self.token.days_left <= 0

    @property
    def headline(self) -> str:
        """``"OK"`` or ``"DEGRADED"`` — the digest / ``/status`` headline word."""
        return "DEGRADED" if self.degraded else "OK"


def _disk_free_pct(path: Path) -> float:
    """Percent free on the filesystem holding ``path`` (0.0 if the total is unknowable)."""
    usage = shutil.disk_usage(path)
    return 100.0 * usage.free / usage.total if usage.total else 0.0


def _marker_time(marker: Path) -> datetime | None:
    """The marker file's mtime as an aware datetime, or ``None`` if it does not exist."""
    if not marker.is_file():
        return None
    return datetime.fromtimestamp(marker.stat().st_mtime).astimezone()


def _context_refreshed_at(path: Path) -> datetime | None:
    """Parse ``refreshed_at`` from the context cache, or ``None`` if absent/unreadable."""
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        return datetime.fromisoformat(str(raw["refreshed_at"]))
    except (ValueError, KeyError, TypeError, OSError):
        return None


def probe_read_api(base: str, *, timeout: float = 3.0) -> bool:
    """Real localhost probe: GET ``base``/health with a tight timeout. Never raises; False on error.

    A hung app stays systemd-``active`` but stops serving; only a real request tells the truth.
    """
    try:
        return requests.get(f"{base}/health", timeout=timeout).status_code == 200
    except requests.RequestException:
        return False


def build_status(
    data_dir: Path,
    *,
    now: datetime,
    today: date | None = None,
    api_base: str = _READ_API_BASE,
    token_expiry: date = UPSTOX_TOKEN_EXPIRY,
    probe: Callable[[str], bool] | None = None,
) -> VmStatus:
    """Assemble the health snapshot from live facts — a PURE read (no writes, no state change).

    Args:
        data_dir: The VM data dir (ingest_state, markers, context cache, oracle_login.json).
        now: The reference instant (IST-aware).
        today: Reference date for the day-counts; defaults to ``now`` in IST.
        api_base: Base URL for the read-API probe.
        token_expiry: The Upstox token's expiry date.
        probe: Read-API probe (injectable for tests); defaults to a real localhost GET /health.

    Returns:
        The assembled :class:`VmStatus` (identical whether called by /status or the digest).
    """
    day = today or now.astimezone(IST).date()
    do_probe = probe or probe_read_api
    state = IngestStateStore(data_dir / "ingest_state.json").current()
    rows = [
        check_ingest(
            "NSE ingest", state.last_success, state.last_attempt_ok, now, max_age=VM_INGEST_MAX_AGE
        ),
        check_context(_context_refreshed_at(data_dir / _CONTEXT_FILE), now),
        check_read_api(do_probe(api_base)),
        check_disk("Disk", _disk_free_pct(data_dir)),
        check_keepalive(
            "Keepalive",
            _marker_time(data_dir / _KEEPALIVE_MARKER),
            now,
            max_age=VM_KEEPALIVE_MAX_AGE,
        ),
        check_bot_listener(_marker_time(data_dir / _BOT_MARKER), now),
    ]
    oracle = assess_oracle_login(read_oracle_login(data_dir / _ORACLE_LOGIN_FILE), day)
    token = assess_token_expiry(token_expiry, day)
    return VmStatus(now, rows, oracle, token)
