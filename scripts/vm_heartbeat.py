"""VM-side heartbeat (v3 V3-3): record a liveness beat + ping the out-of-band monitor. Ships dark.

Runs on the VM after each ingest cycle (systemd timer; the timer commits + pushes the beat file to
the heartbeat git channel the desktop reads). Collects facts — ingest freshness (the BUG-1
``ingest_state``), free disk, the keepalive marker — writes them to ``--beat``, and pings the
liveness monitor if one is configured (``HC_PING_URL``). No monitor configured → it still writes the
local beat and simply skips the ping (dark-ship). It never runs the model.

    python scripts/vm_heartbeat.py --data-dir <vm-data> --beat <channel-clone>/heartbeat.json
"""

from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime
from pathlib import Path

from ipo.core.calendar import now_ist
from ipo.core.logging import configure_logging, get_logger
from ipo.data.ingest.state import IngestStateStore
from ipo.service.vm_health import VmHeartbeat, ping_liveness

_log = get_logger("ipo.service.vm_heartbeat")

KEEPALIVE_MARKER = "keepalive.marker"


def _disk_free_pct(path: Path) -> float:
    usage = shutil.disk_usage(path)
    return 100.0 * usage.free / usage.total if usage.total else 0.0


def _marker_time(marker: Path) -> datetime | None:
    if not marker.is_file():
        return None
    return datetime.fromtimestamp(marker.stat().st_mtime).astimezone()


def build_and_write(data_dir: Path, beat_path: Path, now: datetime) -> VmHeartbeat:
    """Collect the VM's facts and write the heartbeat (the systemd timer commits + pushes it)."""
    state = IngestStateStore(data_dir / "ingest_state.json").current()
    hb = VmHeartbeat(
        beat_at=now,
        ingest_last_success=state.last_success,
        ingest_last_attempt_ok=state.last_attempt_ok,
        disk_free_pct=_disk_free_pct(data_dir),
        keepalive_at=_marker_time(data_dir / KEEPALIVE_MARKER),
    )
    beat_path.parent.mkdir(parents=True, exist_ok=True)
    beat_path.write_text(hb.model_dump_json(indent=2), encoding="utf-8")
    return hb


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write the VM heartbeat + ping the liveness monitor."
    )
    parser.add_argument("--data-dir", required=True, help="the VM data dir (ingest_state, marker)")
    parser.add_argument(
        "--beat", required=True, help="heartbeat.json path in the git channel clone"
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    configure_logging("INFO", json_output=True, file_path=data_dir / "logs" / "heartbeat.log")
    hb = build_and_write(data_dir, Path(args.beat), now_ist())
    pinged = ping_liveness(os.environ.get("HC_PING_URL", "").strip() or None)
    _log.info(
        "vm_heartbeat",
        extra={
            "ingest_ok": hb.ingest_last_attempt_ok,
            "disk_free_pct": round(hb.disk_free_pct, 1),
            "pinged": pinged,
        },
    )


if __name__ == "__main__":
    main()
