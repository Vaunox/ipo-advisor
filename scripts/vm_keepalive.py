"""VM keepalive (v3 V3-3) — a bounded CPU burn so Oracle doesn't reclaim the Always-Free instance.

Oracle reclaims Always-Free compute that AVERAGES idle over a window, so a brief spike doesn't help
and light periodic scraping can look idle and vanish. This runs a SHORT, bounded burn (the systemd
timer runs it ``nice``d, a few minutes at a modest cadence) to keep the utilization average above
the reclaim bar, and touches a marker the heartbeat checks — so a dead keepalive is itself visible
before reclamation. Genuinely-useful activity (the fetch cadence) does most of the work; this is
the top-up, tuned deploy-side against the Oracle console metric (see the runbook).

    python scripts/vm_keepalive.py --data-dir <vm-data> --seconds 120
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

MAX_SECONDS = 600.0  # hard cap so a misconfig can never peg a core indefinitely
MARKER = "keepalive.marker"


def burn(seconds: float) -> int:
    """Busy-loop for ~``seconds`` (keeps one core busy) and return the iteration count. Bounded."""
    end = time.monotonic() + max(0.0, min(seconds, MAX_SECONDS))
    n = 0
    while time.monotonic() < end:
        n = (n + 1) % 1_000_000  # trivial arithmetic — busy without allocating
    return n


def touch_marker(data_dir: Path) -> Path:
    """Record that the keepalive ran (the heartbeat flags a stale marker as a reclaim risk)."""
    marker = data_dir / MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("", encoding="utf-8")
    return marker


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded CPU keepalive + marker touch.")
    parser.add_argument("--data-dir", required=True, help="where to touch the keepalive marker")
    parser.add_argument("--seconds", type=float, default=120.0, help="burn duration (bounded)")
    args = parser.parse_args()
    burn(args.seconds)
    touch_marker(Path(args.data_dir))


if __name__ == "__main__":
    main()
