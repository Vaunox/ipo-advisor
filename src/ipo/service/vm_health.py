"""VM liveness heartbeat + health dimensions (v3 V3-3) — the VM reports facts; readers judge them.

The VM writes a small heartbeat each cycle (the systemd timer commits + pushes it to a git channel
the desktop can read). The desktop's ``run_heartbeat --vm-heartbeat`` reads it and names any failure
HONESTLY — stale beat, failing fetch, low disk, stalled keepalive — never a generic "unhealthy".

That passive detector is PRIMARY, always-on: it needs nothing alive on the VM at check time (a
git-history read) and no VM credentials on the desktop side, so it can't itself fail the way a
monitor-on-the-box would. The thin out-of-band liveness ping (``ping_liveness`` /
``scripts/vm_heartbeat.py``) is a separate, additive backup for the one unrecoverable case the
passive check can't cover in time: Oracle reclaiming the instance. Both ship dark — unconfigured,
neither does anything.

The per-dimension judges here (ingest / disk / keepalive, plus read-API / context / bot-listener /
Oracle-login / token) are the SHARED brain: the VM-side Telegram surface (a new *output* for this
same data, not new monitoring) reuses them verbatim, so the desktop heartbeat and the Telegram
digest can never disagree about a dimension's status or wording.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from pydantic import BaseModel, ValidationError

from ipo.service.heartbeat import OK, STALE, FeedHealth, ago

# Freshness budgets (overridable). Defaults assume a daily VM cycle with a more-frequent keepalive.
BEAT_MAX_AGE = timedelta(hours=30)  # one missed daily cycle + buffer
INGEST_MAX_AGE = timedelta(hours=30)
KEEPALIVE_MAX_AGE = timedelta(hours=30)
DISK_MIN_FREE_PCT = 10.0

# V3-3 Telegram surface — tighter, cadence-sized budgets + new dims. The digest/alerts reuse the
# SAME judges below: a new surface for the health data, not new monitoring.
VM_INGEST_MAX_AGE = timedelta(minutes=90)  # 30-min ingest cadence → flag after ~3 missed cycles
CONTEXT_MAX_AGE = timedelta(
    hours=16
)  # 3x/day (08:15/13:15/18:15 IST); clears the ~14h overnight gap
BOT_MARKER_MAX_AGE = timedelta(minutes=5)  # bot.marker touched every ~50s poll → ~6 missed = down
VM_KEEPALIVE_MAX_AGE = timedelta(hours=1)  # keepalive runs every 30 min → flag after ~2 missed
ORACLE_WARN_DAYS = 21
ORACLE_URGENT_DAYS = 27
ORACLE_RECLAIM_DAYS = 30


class VmHeartbeat(BaseModel):
    """The facts the VM records each cycle; the read side (``check_vm_heartbeat``) judges them."""

    beat_at: datetime
    ingest_last_success: datetime | None = None
    ingest_last_attempt_ok: bool | None = None
    disk_free_pct: float = 100.0
    keepalive_at: datetime | None = None


def read_heartbeat(path: Path) -> VmHeartbeat | None:
    """Load the VM's last heartbeat (``None`` if absent). Corrupt content reads as absent."""
    if not path.is_file():
        return None
    try:
        return VmHeartbeat.model_validate_json(path.read_text(encoding="utf-8-sig"))
    except (ValueError, ValidationError):
        return None


# --- per-dimension judges (shared by the desktop heartbeat AND the VM Telegram snapshot) ------


def check_ingest(
    name: str,
    last_success: datetime | None,
    last_attempt_ok: bool | None,
    now: datetime,
    *,
    max_age: timedelta,
) -> FeedHealth:
    """Judge NSE ingest freshness — the failing-fetch / 'NSE blocking the datacenter IP' case."""
    if last_success is None:
        return FeedHealth(name, STALE, "no successful NSE fetch on record")
    age = now - last_success
    if age > max_age:
        tail = " (latest attempt failed)" if last_attempt_ok is False else ""
        return FeedHealth(name, STALE, f"NSE fetch failing — last good pull {ago(age)} ago{tail}")
    return FeedHealth(name, OK, f"last good pull {ago(age)} ago")


def check_disk(
    name: str, disk_free_pct: float, *, min_free_pct: float = DISK_MIN_FREE_PCT
) -> FeedHealth:
    """Judge free disk — the 'disk fills, writes fail' case."""
    if disk_free_pct < min_free_pct:
        detail = f"{disk_free_pct:.0f}% free — below {min_free_pct:.0f}% (writes may fail)"
        return FeedHealth(name, STALE, detail)
    return FeedHealth(name, OK, f"{disk_free_pct:.0f}% free")


def check_keepalive(
    name: str, keepalive_at: datetime | None, now: datetime, *, max_age: timedelta
) -> FeedHealth:
    """Judge the keepalive marker — a dead keepalive is itself an Oracle-reclaim risk."""
    if keepalive_at is None:
        return FeedHealth(name, STALE, "keepalive has not run — Oracle reclaim risk")
    age = now - keepalive_at
    if age > max_age:
        return FeedHealth(name, STALE, f"keepalive last ran {ago(age)} ago — Oracle reclaim risk")
    return FeedHealth(name, OK, f"keepalive {ago(age)} ago")


def check_vm_heartbeat(
    hb: VmHeartbeat | None,
    now: datetime,
    *,
    beat_max_age: timedelta = BEAT_MAX_AGE,
    ingest_max_age: timedelta = INGEST_MAX_AGE,
    keepalive_max_age: timedelta = KEEPALIVE_MAX_AGE,
    disk_min_free_pct: float = DISK_MIN_FREE_PCT,
) -> list[FeedHealth]:
    """Judge a VM heartbeat, naming each failure honestly; healthy dimensions read OK.

    A None/absent heartbeat, or one older than ``beat_max_age``, is a dominant STALE row — the VM
    may be dead, so its facts can't be trusted. Otherwise each fact (ingest, disk, keepalive) is
    judged on its own via the shared judges, so the operator sees exactly which one failed.
    """
    if hb is None:
        return [
            FeedHealth(
                "VM heartbeat", STALE, "no heartbeat found — VM not reporting (dead, or not synced)"
            )
        ]
    beat_age = now - hb.beat_at
    if beat_age > beat_max_age:
        return [
            FeedHealth(
                "VM heartbeat",
                STALE,
                f"last beat {ago(beat_age)} ago — the VM's fetch cycle may have stopped",
            )
        ]
    return [
        FeedHealth("VM heartbeat", OK, f"last beat {ago(beat_age)} ago"),
        check_ingest(
            "VM ingest",
            hb.ingest_last_success,
            hb.ingest_last_attempt_ok,
            now,
            max_age=ingest_max_age,
        ),
        check_disk("VM disk", hb.disk_free_pct, min_free_pct=disk_min_free_pct),
        check_keepalive("VM keepalive", hb.keepalive_at, now, max_age=keepalive_max_age),
    ]


def vm_degraded(rows: list[FeedHealth]) -> bool:
    """True if any VM check is not OK — drives the heartbeat's non-zero exit (fail loud)."""
    return any(not r.ok for r in rows)


def ping_liveness(url: str | None, *, timeout: float = 10.0) -> bool:
    """Best-effort out-of-band liveness ping (dead-man's switch). Dark-ship: no URL → skip.

    A ping failure must NEVER break the VM cycle, so every error is swallowed. The monitor alerts on
    the ABSENCE of pings (the VM being gone), so a single missed ping is harmless. Returns whether a
    ping was actually sent (``False`` when unconfigured or the request failed).
    """
    if not url:
        return False  # dark-ship: no monitor configured
    try:
        requests.get(url, timeout=timeout)
        return True
    except requests.RequestException:
        return False


# --- V3-3 Telegram surface: extra dims + the Oracle-login countdown (single source) -----------


def check_read_api(reachable: bool) -> FeedHealth:
    """Judge the read-API from a REAL probe result (a live GET /health, not a unit-active check).

    A hung app is ``active`` under systemd yet not serving; only a real request distinguishes them,
    so callers pass the outcome of a real localhost probe.
    """
    if reachable:
        return FeedHealth("Read-API", OK, "up")
    return FeedHealth("Read-API", STALE, "not responding on :8000")


def check_context(
    last_refresh: datetime | None, now: datetime, *, max_age: timedelta = CONTEXT_MAX_AGE
) -> FeedHealth:
    """Judge Upstox context freshness (the 3x/day cache) — honest when it stops refreshing."""
    if last_refresh is None:
        return FeedHealth("Upstox ctx", STALE, "no context refresh on record")
    age = now - last_refresh
    if age > max_age:
        return FeedHealth(
            "Upstox ctx", STALE, f"context refresh failing — last good {ago(age)} ago"
        )
    return FeedHealth("Upstox ctx", OK, f"refreshed {ago(age)} ago")


def check_bot_listener(
    marker_at: datetime | None, now: datetime, *, max_age: timedelta = BOT_MARKER_MAX_AGE
) -> FeedHealth:
    """Judge the command listener from its poll marker — a dead listener is its own failure."""
    if marker_at is None:
        return FeedHealth("Commands", STALE, "command listener not running")
    age = now - marker_at
    if age > max_age:
        return FeedHealth("Commands", STALE, f"listener silent {ago(age)} — may be down")
    return FeedHealth("Commands", OK, "listening")


@dataclass(frozen=True)
class OracleLoginHealth:
    """The one source of truth for the Oracle-console login countdown (tier + day-count + its row).

    ``tier`` is ``"none"`` (never recorded), ``"ok"`` (< warn), ``"warn"`` (>= 21d), or ``"urgent"``
    (>= 27d). All three readers — ``/status``, the digest line, the alert crossing-detector — use
    this one assessment, so the thresholds live in exactly one place and the surfaces can't disagree
    about the day count.
    """

    tier: str
    days_ago: int | None
    last_login: date | None
    feed: FeedHealth


def assess_oracle_login(last_login: date | None, today: date) -> OracleLoginHealth:
    """Assess the Oracle-login countdown against the 21/27-day reclaim tiers — the single source.

    A *missing* record is treated as worse than a stale one — a first-class ``"none"`` tier that
    renders as an active prompt — because an un-tracked login is the higher reclaim risk. Evaluated
    fresh at each render from ``oracle_login.json``; never duplicated across the three readers.
    """
    if last_login is None:
        feed = FeedHealth(
            "Oracle login", STALE, "none recorded — run /login to start the 30-day countdown"
        )
        return OracleLoginHealth("none", None, None, feed)
    days = (today - last_login).days
    if days >= ORACLE_URGENT_DAYS:
        detail = f"{days} days ago — log in NOW or the VM may be reclaimed"
        return OracleLoginHealth(
            "urgent", days, last_login, FeedHealth("Oracle login", STALE, detail)
        )
    if days >= ORACLE_WARN_DAYS:
        detail = f"{days} days ago — log in soon or the VM may be reclaimed"
        return OracleLoginHealth(
            "warn", days, last_login, FeedHealth("Oracle login", STALE, detail)
        )
    feed = FeedHealth("Oracle login", OK, f"{days} days ago")
    return OracleLoginHealth("ok", days, last_login, feed)


@dataclass(frozen=True)
class TokenExpiry:
    """The Upstox token expiry countdown (informational; a fixed annual read-only credential)."""

    expiry: date
    days_left: int
    feed: FeedHealth


def assess_token_expiry(expiry: date, today: date, *, warn_days: int = 30) -> TokenExpiry:
    """Days until the Upstox token expires; STALE only in the warn window (else informational)."""
    days_left = (expiry - today).days
    if days_left <= 0:
        return TokenExpiry(expiry, days_left, FeedHealth("Upstox token", STALE, "EXPIRED"))
    if days_left <= warn_days:
        feed = FeedHealth("Upstox token", STALE, f"expires in {days_left} days")
        return TokenExpiry(expiry, days_left, feed)
    return TokenExpiry(expiry, days_left, FeedHealth("Upstox token", OK, f"{days_left} days left"))
