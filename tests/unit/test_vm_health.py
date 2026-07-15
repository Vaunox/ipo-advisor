"""VM liveness heartbeat (v3 V3-3) — the detector, the writer, and the keepalive.

The headline proof (operator's ask): the --vm-heartbeat detector FIRES on a stale heartbeat and
stays QUIET on a fresh one. Plus: every failure names itself honestly (never a generic "unhealthy"),
a missing/corrupt beat reads as stale, the out-of-band ping ships dark, and the writer + keepalive
work. Offline + deterministic.
"""

from __future__ import annotations

import importlib.util
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

from ipo.service.heartbeat import OK, STALE
from ipo.service.vm_health import (
    VmHeartbeat,
    assess_oracle_login,
    assess_token_expiry,
    check_bot_listener,
    check_context,
    check_read_api,
    check_vm_heartbeat,
    ping_liveness,
    read_heartbeat,
    vm_degraded,
)

_IST = timezone(timedelta(hours=5, minutes=30))
_NOW = datetime(2026, 7, 15, 12, 0, tzinfo=_IST)


def _load_script(name: str) -> ModuleType:
    """Load a scripts/*.py module by path (scripts is not an importable package)."""
    path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fresh() -> VmHeartbeat:
    return VmHeartbeat(
        beat_at=_NOW - timedelta(minutes=10),
        ingest_last_success=_NOW - timedelta(hours=1),
        ingest_last_attempt_ok=True,
        disk_free_pct=55.0,
        keepalive_at=_NOW - timedelta(minutes=30),
    )


# --- the detector: fires on stale, quiet on fresh (the headline) -------------------------------


def test_detector_stays_quiet_on_a_fresh_healthy_heartbeat() -> None:
    rows = check_vm_heartbeat(_fresh(), _NOW)
    assert not vm_degraded(rows)  # QUIET — nothing fires
    assert all(r.status == OK for r in rows)


def test_detector_fires_on_a_stale_heartbeat() -> None:
    hb = _fresh().model_copy(update={"beat_at": _NOW - timedelta(hours=40)})
    rows = check_vm_heartbeat(hb, _NOW)
    assert vm_degraded(rows)  # FIRES
    assert rows[0].status == STALE
    assert "last beat" in rows[0].detail and "may have stopped" in rows[0].detail


def test_detector_fires_on_a_missing_heartbeat() -> None:
    rows = check_vm_heartbeat(None, _NOW)
    assert vm_degraded(rows)
    assert "not reporting" in rows[0].detail  # names WHY, not a generic "unhealthy"


# --- every failure names itself honestly (hold #2) ---------------------------------------------


def test_failing_fetch_is_named_not_generic() -> None:
    hb = _fresh().model_copy(
        update={"ingest_last_success": _NOW - timedelta(hours=40), "ingest_last_attempt_ok": False}
    )
    detail = next(r.detail for r in check_vm_heartbeat(hb, _NOW) if r.name == "VM ingest")
    assert "NSE fetch failing" in detail and "latest attempt failed" in detail


def test_low_disk_is_named() -> None:
    hb = _fresh().model_copy(update={"disk_free_pct": 4.0})
    row = next(r for r in check_vm_heartbeat(hb, _NOW) if r.name == "VM disk")
    assert row.status == STALE and "% free" in row.detail


def test_stalled_keepalive_names_the_reclaim_risk() -> None:
    hb = _fresh().model_copy(update={"keepalive_at": _NOW - timedelta(hours=40)})
    row = next(r for r in check_vm_heartbeat(hb, _NOW) if r.name == "VM keepalive")
    assert row.status == STALE and "reclaim risk" in row.detail


def test_one_failing_dimension_does_not_mask_the_others_being_ok() -> None:
    hb = _fresh().model_copy(update={"disk_free_pct": 2.0})
    rows = check_vm_heartbeat(hb, _NOW)
    assert {r.name for r in rows if r.status == OK} >= {"VM heartbeat", "VM ingest", "VM keepalive"}
    assert vm_degraded(rows)  # still degraded overall


# --- read + ping ------------------------------------------------------------------------------


def test_read_heartbeat_absent_and_corrupt_read_as_none(tmp_path: Path) -> None:
    assert read_heartbeat(tmp_path / "nope.json") is None
    bad = tmp_path / "heartbeat.json"
    bad.write_text("{ truncated", encoding="utf-8")
    assert read_heartbeat(bad) is None  # corrupt → None → the detector treats it as stale


def test_read_heartbeat_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "heartbeat.json"
    path.write_text(_fresh().model_dump_json(), encoding="utf-8")
    assert read_heartbeat(path) == _fresh()


def test_ping_liveness_ships_dark_without_a_url() -> None:
    assert ping_liveness(None) is False  # no network touched
    assert ping_liveness("") is False


# --- the scripts: writer + keepalive ----------------------------------------------------------


def test_vm_heartbeat_writer_reflects_ingest_state(tmp_path: Path) -> None:
    from ipo.data.ingest.state import IngestStateStore

    data = tmp_path / "data"
    state = IngestStateStore(data / "ingest_state.json")
    state.record_success(_NOW - timedelta(minutes=20))
    (data / "keepalive.marker").write_text("", encoding="utf-8")

    writer = _load_script("vm_heartbeat")
    beat = tmp_path / "channel" / "heartbeat.json"
    hb = writer.build_and_write(data, beat, _NOW)

    assert beat.is_file()
    loaded = read_heartbeat(beat)
    assert loaded == hb  # what was written round-trips to what was returned
    assert loaded is not None
    assert loaded.beat_at == _NOW
    assert loaded.ingest_last_attempt_ok is True
    assert loaded.keepalive_at is not None
    assert 0.0 <= loaded.disk_free_pct <= 100.0
    # a freshly-written beat reads as healthy
    assert not vm_degraded(check_vm_heartbeat(loaded, _NOW))


def test_keepalive_burns_bounded_and_touches_marker(tmp_path: Path) -> None:
    keepalive = _load_script("vm_keepalive")
    assert isinstance(keepalive.burn(0.02), int)  # returns, does not hang
    marker = keepalive.touch_marker(tmp_path)
    assert marker.is_file() and marker.name == "keepalive.marker"


def test_keepalive_burn_is_hard_capped(tmp_path: Path) -> None:
    keepalive = _load_script("vm_keepalive")
    assert keepalive.MAX_SECONDS <= 600.0  # a misconfig can never peg a core indefinitely


# --- V3-3 Telegram-surface dimensions + the Oracle-login countdown (single source) -------------


def test_read_api_probe_result_is_honest() -> None:
    assert check_read_api(True).status == OK
    down = check_read_api(False)
    assert down.status == STALE and "not responding" in down.detail


def test_context_freshness_is_named() -> None:
    assert check_context(None, _NOW).status == STALE  # never refreshed
    stale = check_context(_NOW - timedelta(hours=20), _NOW)
    assert stale.status == STALE and "context refresh failing" in stale.detail
    assert check_context(_NOW - timedelta(hours=3), _NOW).status == OK


def test_bot_listener_tolerates_a_normal_poll_gap_but_flags_silence() -> None:
    assert check_bot_listener(None, _NOW).status == STALE  # not running
    assert check_bot_listener(_NOW - timedelta(seconds=50), _NOW).status == OK  # normal poll gap
    dead = check_bot_listener(_NOW - timedelta(minutes=10), _NOW)
    assert dead.status == STALE and "may be down" in dead.detail


def test_oracle_login_never_recorded_is_first_class() -> None:
    h = assess_oracle_login(None, date(2026, 7, 15))
    assert h.tier == "none" and h.days_ago is None
    assert not h.feed.ok and "none recorded" in h.feed.detail and "/login" in h.feed.detail


def test_oracle_login_tiers_at_the_thresholds() -> None:
    today = date(2026, 7, 15)
    assert assess_oracle_login(today - timedelta(days=2), today).tier == "ok"
    assert assess_oracle_login(today - timedelta(days=20), today).tier == "ok"
    assert assess_oracle_login(today - timedelta(days=21), today).tier == "warn"
    assert assess_oracle_login(today - timedelta(days=26), today).tier == "warn"
    assert assess_oracle_login(today - timedelta(days=27), today).tier == "urgent"


def test_oracle_login_warn_and_urgent_are_not_ok() -> None:
    today = date(2026, 7, 15)
    assert not assess_oracle_login(today - timedelta(days=21), today).feed.ok
    urgent = assess_oracle_login(today - timedelta(days=30), today)
    assert "log in NOW" in urgent.feed.detail


def test_token_expiry_informational_until_the_warn_window() -> None:
    today = date(2026, 7, 15)
    healthy = assess_token_expiry(date(2027, 7, 1), today)
    assert healthy.feed.ok and healthy.days_left == 351
    assert assess_token_expiry(today + timedelta(days=10), today).feed.status == STALE
    assert assess_token_expiry(today - timedelta(days=1), today).feed.detail == "EXPIRED"
