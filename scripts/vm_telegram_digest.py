"""VM Telegram digest — the periodic health digest (v3 V3-3). Dark-ships without creds.

Runs on a systemd timer (4×/day: 00:00 / 06:00 / 12:00 / 18:00 IST). Builds the VmStatus snapshot,
renders the digest (with the alert-check's "N consecutive since" notes), and sends it
UNCONDITIONALLY (OK or DEGRADED) — the periodic reconciler, distinct from the transition-only
alert-check.

SINGLE WRITER: the digest writes NOTHING — pure build -> render -> send. It only reads
(ingest_state, markers, context, oracle_login, alert_state). Unconfigured -> a no-op that sends
nothing.

    python scripts/vm_telegram_digest.py --data-dir /opt/ipo/data
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ipo.core.calendar import now_ist
from ipo.core.logging import configure_logging, get_logger
from ipo.service.telegram import send_telegram, telegram_env
from ipo.service.telegram_alerts import load_alert_state, since_notes
from ipo.service.telegram_format import format_digest
from ipo.service.vm_status import build_status

_log = get_logger("ipo.scripts.vm_telegram_digest")

_ALERT_STATE = "alert_state.json"


def run_digest(
    data_dir: Path,
    *,
    now: datetime | None = None,
    probe: Callable[[str], bool] | None = None,
) -> bool:
    """Build -> render -> send the digest (unconditional). Dark-ship no-op if unconfigured; sent?"""
    token, chat_id = telegram_env()
    if not token or not chat_id:
        _log.info("telegram_digest_darkship")
        return False
    status = build_status(data_dir, now=now or now_ist(), probe=probe)
    notes = since_notes(load_alert_state(data_dir / _ALERT_STATE))
    return send_telegram(token, chat_id, format_digest(status, since_by_key=notes))


def main() -> None:
    parser = argparse.ArgumentParser(description="Send the periodic VM health digest.")
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    configure_logging("INFO", json_output=True, file_path=data_dir / "logs" / "telegram_digest.log")
    run_digest(data_dir)


if __name__ == "__main__":
    main()
