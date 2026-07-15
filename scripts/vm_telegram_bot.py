"""VM Telegram bot — the long-poll command daemon (v3 V3-3). Dark-ships without creds.

Always-on systemd service (Type=simple, Restart=always). Each cycle long-polls getUpdates,
dispatches /status + /login to handle_update (owner-only), sends replies, and touches bot.marker
as proof-of-life (the independent alert-check flags a stale marker as a dead listener). The
getUpdates offset advances past each processed update so nothing is reprocessed; a restart
re-reading an old update is harmless because both commands are idempotent.

SINGLE WRITER: this daemon is the ONLY writer of bot.marker and oracle_login.json (the latter via
an authorised /login); it never writes alert_state.json (alert-check owns that). Unconfigured -> it
logs and returns WITHOUT entering the poll loop (no spin). It emits no sd_notify, so systemd
WatchdogSec is unused; a hung daemon is caught out-of-band by the alert-check (stale marker), and
Restart=always recovers a crash.

    python scripts/vm_telegram_bot.py --data-dir /opt/ipo/data
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ipo.core.calendar import now_ist
from ipo.core.logging import configure_logging, get_logger
from ipo.service.telegram import get_updates, send_telegram, telegram_env
from ipo.service.telegram_alerts import load_alert_state, since_notes
from ipo.service.telegram_commands import handle_update
from ipo.service.telegram_format import format_status
from ipo.service.vm_status import build_status

_log = get_logger("ipo.scripts.vm_telegram_bot")

_BOT_MARKER = "bot.marker"
_ALERT_STATE = "alert_state.json"


def _touch(marker: Path) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("", encoding="utf-8")


def _render_status(data_dir: Path) -> str:
    # /status renders the SAME snapshot the digest does (read-only), incl. the alert-check's notes.
    status = build_status(data_dir, now=now_ist())
    notes = since_notes(load_alert_state(data_dir / _ALERT_STATE))
    return format_status(status, since_by_key=notes)


def poll_once(token: str, chat_id: int, offset: int | None, *, data_dir: Path) -> int | None:
    """One long-poll cycle: fetch, dispatch, reply, touch marker; return the next offset (acked)."""
    next_offset = offset
    for update in get_updates(token, offset):
        uid = update.get("update_id")
        if isinstance(uid, int):
            next_offset = uid + 1  # ack past this update so it is not reprocessed
        reply = handle_update(
            update,
            authorized_chat_id=chat_id,
            data_dir=data_dir,
            now=now_ist(),
            render_status=lambda: _render_status(data_dir),
        )
        if reply is not None:
            send_telegram(token, chat_id, reply)
    _touch(data_dir / _BOT_MARKER)  # proof-of-life every cycle (owned write)
    return next_offset


def run_daemon(data_dir: Path, *, poll_limit: int | None = None) -> None:
    """Long-poll forever (or ``poll_limit`` cycles for tests). Dark-ship no-op if unconfigured."""
    token, chat_id = telegram_env()
    if not token or not chat_id:
        _log.info("telegram_bot_darkship_no_creds")
        return
    try:
        cid = int(chat_id)
    except ValueError:
        _log.warning("telegram_bot_bad_chat_id")
        return
    offset: int | None = None
    count = 0
    while poll_limit is None or count < poll_limit:
        offset = poll_once(token, cid, offset, data_dir=data_dir)
        count += 1


def main() -> None:
    parser = argparse.ArgumentParser(description="VM Telegram command daemon (long-poll).")
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    configure_logging("INFO", json_output=True, file_path=data_dir / "logs" / "telegram_bot.log")
    run_daemon(data_dir)


if __name__ == "__main__":
    main()
