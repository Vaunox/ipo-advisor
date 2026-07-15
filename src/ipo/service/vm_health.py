"""VM liveness heartbeat (v3 V3-3) — the VM reports facts; the desktop judges them.

The VM writes a small heartbeat each cycle (the systemd timer commits + pushes it to a git channel
the desktop can read). The desktop's ``run_heartbeat --vm-heartbeat`` reads it and names any failure
HONESTLY — stale beat, failing fetch, low disk, stalled keepalive — never a generic "unhealthy".

This is the PRIMARY, always-on detector: it needs nothing alive on the VM at check time (a
git-history read) and no VM credentials on the desktop side, so it can't itself fail the way a
monitor-on-the-box would. The thin out-of-band liveness ping (``ping_liveness`` /
``scripts/vm_heartbeat.py``) is a separate, purely additive backup for the one unrecoverable case
the passive check can't cover in time: Oracle reclaiming the instance. Both ship dark —
unconfigured, neither does anything.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import requests
from pydantic import BaseModel, ValidationError

from ipo.service.heartbeat import OK, STALE, FeedHealth, ago

# Freshness budgets (overridable). Defaults assume a daily VM cycle with a more-frequent keepalive.
BEAT_MAX_AGE = timedelta(hours=30)  # one missed daily cycle + buffer
INGEST_MAX_AGE = timedelta(hours=30)
KEEPALIVE_MAX_AGE = timedelta(hours=30)
DISK_MIN_FREE_PCT = 10.0


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

    A None/absent heartbeat, or one older than ``beat_max_age``, is a single dominant STALE row —
    the VM may be dead, so its inner facts can't be trusted. Otherwise each fact (ingest, disk,
    keepalive) is judged on its own so the operator sees exactly which one failed.
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

    rows = [FeedHealth("VM heartbeat", OK, f"last beat {ago(beat_age)} ago")]

    # Ingest freshness — the "NSE blocking the datacenter IP" case.
    if hb.ingest_last_success is None:
        rows.append(FeedHealth("VM ingest", STALE, "no successful NSE fetch on record"))
    else:
        ingest_age = now - hb.ingest_last_success
        if ingest_age > ingest_max_age:
            tail = " (latest attempt failed)" if hb.ingest_last_attempt_ok is False else ""
            rows.append(
                FeedHealth(
                    "VM ingest",
                    STALE,
                    f"NSE fetch failing — last good pull {ago(ingest_age)} ago{tail}",
                )
            )
        else:
            rows.append(FeedHealth("VM ingest", OK, f"last good pull {ago(ingest_age)} ago"))

    # Disk — the "disk fills" case.
    if hb.disk_free_pct < disk_min_free_pct:
        rows.append(
            FeedHealth(
                "VM disk",
                STALE,
                f"{hb.disk_free_pct:.0f}% free — below {disk_min_free_pct:.0f}% (writes may fail)",
            )
        )
    else:
        rows.append(FeedHealth("VM disk", OK, f"{hb.disk_free_pct:.0f}% free"))

    # Keepalive — the Oracle-reclaim guard (a dead keepalive is itself a reclaim risk).
    if hb.keepalive_at is None:
        rows.append(
            FeedHealth("VM keepalive", STALE, "keepalive has not run — Oracle reclaim risk")
        )
    else:
        ka_age = now - hb.keepalive_at
        if ka_age > keepalive_max_age:
            rows.append(
                FeedHealth(
                    "VM keepalive",
                    STALE,
                    f"keepalive last ran {ago(ka_age)} ago — Oracle reclaim risk",
                )
            )
        else:
            rows.append(FeedHealth("VM keepalive", OK, f"keepalive {ago(ka_age)} ago"))

    return rows


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
