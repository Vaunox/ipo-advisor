"""VM Telegram alert-check — independent transition detector (v3 V3-3). Dark-ships without creds.

Runs on a short systemd timer (~15-30 min), SEPARATE from the bot daemon — so it fires "listener
down" when the daemon itself is dead (a dead sender can't announce its own death). It builds the
snapshot, diffs the conditions against alert_state.json, sends ONE alert per edge (break /
recovered), and persists the new state. Diff-only: nothing is sent when nothing changed.

SINGLE WRITER: alert-check is the ONLY writer of alert_state.json; it never touches bot.marker or
oracle_login.json. Unconfigured -> a no-op that neither sends nor writes.

    python scripts/vm_alert_check.py --data-dir /opt/ipo/data
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ipo.core.calendar import now_ist
from ipo.core.logging import configure_logging, get_logger
from ipo.service.telegram import send_telegram, telegram_env
from ipo.service.telegram_alerts import (
    conditions,
    diff_transitions,
    load_alert_state,
    save_alert_state,
)
from ipo.service.telegram_format import format_alert
from ipo.service.vm_status import build_status

_log = get_logger("ipo.scripts.vm_alert_check")

_ALERT_STATE = "alert_state.json"


def run_alert_check(
    data_dir: Path,
    *,
    now: datetime | None = None,
    probe: Callable[[str], bool] | None = None,
) -> list[str]:
    """Build -> diff -> send transitions -> save state. Dark-ship no-op; returns alerted keys."""
    token, chat_id = telegram_env()
    if not token or not chat_id:
        _log.info("telegram_alertcheck_darkship")
        return []
    when = now or now_ist()
    status = build_status(data_dir, now=when, probe=probe)
    state_path = data_dir / _ALERT_STATE
    transitions, new_state = diff_transitions(
        load_alert_state(state_path), conditions(status), when
    )
    save_alert_state(state_path, new_state)  # the ONLY owned write
    sent: list[str] = []
    for transition in transitions:
        if send_telegram(token, chat_id, format_alert(transition)):
            sent.append(transition.key)
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check health + send state-change Telegram alerts."
    )
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    configure_logging(
        "INFO", json_output=True, file_path=data_dir / "logs" / "telegram_alert_check.log"
    )
    run_alert_check(data_dir)


if __name__ == "__main__":
    main()
