"""VM status snapshot (v3 V3-3) — a pure read; the headline folds in the Oracle-login tiers.

build_status only reads (ingest state, markers, context, oracle-login) plus an injected probe, so a
build writes/touches nothing — that side-effect-freeness is what lets /status and the digest render
from the same snapshot. The headline flips DEGRADED on a broken operational dim, a missing Oracle
login, or the 27-day tier — but NOT on a healthy VM whose only note is a sub-21-day login.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from ipo.core.constants import IST
from ipo.data.ingest.state import IngestStateStore
from ipo.service.oracle_login import record_oracle_login
from ipo.service.vm_status import build_status

_NOW = datetime(2026, 7, 15, 18, 0, tzinfo=IST)


def _healthy(data: Path, *, login_days_ago: int = 2) -> None:
    """Lay down a fully-healthy data dir: fresh ingest, markers, context, and a recent login."""
    IngestStateStore(data / "ingest_state.json").record_success(_NOW - timedelta(minutes=10))
    for marker in ("keepalive.marker", "bot.marker"):
        path = data / marker
        path.write_text("", encoding="utf-8")
        os.utime(path, (_NOW.timestamp(), _NOW.timestamp()))  # pin mtime → deterministic freshness
    ctx = data / "context" / "ipo_context.json"
    ctx.parent.mkdir(parents=True, exist_ok=True)
    refreshed = (_NOW - timedelta(hours=3)).isoformat()
    ctx.write_text(f'{{"refreshed_at": "{refreshed}", "ipos": {{}}}}', encoding="utf-8")
    record_oracle_login(data / "oracle_login.json", now=_NOW - timedelta(days=login_days_ago))


def _up(_base: str) -> bool:
    return True


def _down(_base: str) -> bool:
    return False


def test_healthy_vm_reads_ok_and_writes_nothing(tmp_path: Path) -> None:
    _healthy(tmp_path)
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    status = build_status(tmp_path, now=_NOW, probe=_up)
    after = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    assert status.headline == "OK" and not status.degraded
    assert before == after  # PURE read — build_status wrote or touched nothing


def test_read_api_down_flips_degraded(tmp_path: Path) -> None:
    _healthy(tmp_path)
    status = build_status(tmp_path, now=_NOW, probe=_down)
    assert status.degraded and status.headline == "DEGRADED"
    api = next(r for r in status.rows if r.name == "Read-API")
    assert not api.ok and "not responding" in api.detail


def test_missing_oracle_login_flips_degraded(tmp_path: Path) -> None:
    _healthy(tmp_path)
    (tmp_path / "oracle_login.json").unlink()  # never recorded
    status = build_status(tmp_path, now=_NOW, probe=_up)
    assert status.oracle.tier == "none"
    assert status.degraded  # a missing login is worse than a stale one — it flips the headline


def test_warn_login_does_not_degrade_but_urgent_does(tmp_path: Path) -> None:
    _healthy(tmp_path, login_days_ago=22)  # warn tier (>= 21)
    warn = build_status(tmp_path, now=_NOW, probe=_up)
    assert warn.oracle.tier == "warn"
    assert not warn.degraded  # a 21-day warning shows on its line but does not degrade the headline

    _healthy(tmp_path, login_days_ago=28)  # urgent tier (>= 27)
    urgent = build_status(tmp_path, now=_NOW, probe=_up)
    assert urgent.oracle.tier == "urgent" and urgent.degraded
