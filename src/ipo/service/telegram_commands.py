"""Inbound command handling for the VM Telegram bot (v3 V3-3) — /status and /login, owner-only.

The long-poll daemon passes each Telegram update here. Authorisation is strict: only messages from
``TELEGRAM_CHAT_ID`` are acted on; other chats are silently dropped (no reply, no ack) — a /login
from a stranger must be a no-op since /login writes state. /status is read-only and renders through
the SAME renderer as the digest. /login records today's IST date to ``oracle_login.json``, ISO on
disk, and is idempotent: re-processing writes the same date.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ipo.core.logging import get_logger
from ipo.service.oracle_login import record_oracle_login
from ipo.service.telegram_format import format_login_confirmation

_log = get_logger("ipo.service.telegram_commands")

# Single source of truth for the "/" menu (Telegram setMyCommands) AND the fallback help below — so
# the popup list and what handle_update dispatches can't drift apart.
COMMANDS: tuple[tuple[str, str], ...] = (
    ("status", "VM Status"),
    ("login", "Oracle Login Confirmation"),
)

_HELP = "Commands: " + " · ".join(f"/{name}" for name, _ in COMMANDS)
_ORACLE_LOGIN_FILE = "oracle_login.json"


def _message_fields(update: dict[str, object]) -> tuple[int, str] | None:
    """Pull ``(chat_id, text)`` from a Telegram update; ``None`` if not a text message."""
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return None
    chat_id = chat.get("id")
    text = message.get("text")
    if not isinstance(chat_id, int) or not isinstance(text, str):
        return None
    return chat_id, text


def handle_update(
    update: dict[str, object],
    *,
    authorized_chat_id: int,
    data_dir: Path,
    now: datetime,
    render_status: Callable[[], str],
) -> str | None:
    """Handle one inbound update; return the reply text, or ``None`` to send nothing.

    Owner-only: a chat id other than ``authorized_chat_id`` is silently dropped (no reply, no ack,
    debug-log only) — including a /login, which must not write state for a stranger. /status returns
    the rendered snapshot (read-only); /login records today's IST date and confirms; anything else
    from the owner gets a one-line help.

    Args:
        update: A Telegram update object (from ``get_updates``).
        authorized_chat_id: The only chat id whose commands are acted on.
        data_dir: The VM data dir (where ``/login`` writes ``oracle_login.json``).
        now: The reference instant (IST) used for the ``/login`` date.
        render_status: Builds + renders the ``/status`` snapshot (same renderer as the digest).

    Returns:
        The reply string to send, or ``None`` to send nothing.
    """
    fields = _message_fields(update)
    if fields is None:
        return None
    chat_id, text = fields
    if chat_id != authorized_chat_id:
        _log.debug("telegram_unauthorized", extra={"chat_id": chat_id})
        return None
    parts = text.strip().split()
    command = parts[0].split("@")[0].lower() if parts else ""
    if not command:
        return None  # empty/whitespace message from the owner — nothing to do
    if command == "/status":
        return render_status()
    if command == "/login":
        return format_login_confirmation(
            record_oracle_login(data_dir / _ORACLE_LOGIN_FILE, now=now)
        )
    return _HELP
