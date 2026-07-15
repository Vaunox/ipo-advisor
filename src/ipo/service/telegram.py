"""Telegram Bot API client (v3 V3-3) — strictly additive, dark-ship, never raises.

The VM's only outbound Telegram surface: ``send_telegram`` (one ``sendMessage`` POST) and
``get_updates`` (long-poll ``getUpdates`` for the interactive commands). Both are outbound-only
HTTPS to ``api.telegram.org`` — no inbound port, webhook, or TLS to manage. Long-poll beats a
webhook on this tight-ingress, IP-only VM.

Every failure is swallowed and logged: a network blip, a non-200, or a malformed body must never
crash the health job, the ingest cycle, the context refresh, or the read API. Unconfigured (no
token or no chat id) is a silent no-op, so the feature ships dark until the operator sets the env.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable

import requests

from ipo.core.logging import get_logger

_log = get_logger("ipo.service.telegram")

_API = "https://api.telegram.org"
_SEND_TIMEOUT = 10.0
_LONGPOLL_SECONDS = 50


def telegram_env() -> tuple[str | None, str | None]:
    """Read the bot token and chat id from the environment (systemd ``EnvironmentFile``).

    Returns:
        ``(token, chat_id)``; either is ``None`` when unset, making the client a dark-ship no-op.
    """
    return (
        os.environ.get("TELEGRAM_BOT_TOKEN") or None,
        os.environ.get("TELEGRAM_CHAT_ID") or None,
    )


def send_telegram(
    token: str | None,
    chat_id: str | int | None,
    text: str,
    *,
    parse_mode: str = "HTML",
    retries: int = 2,
    timeout: float = _SEND_TIMEOUT,
) -> bool:
    """POST one message to Telegram; return whether it was delivered. Never raises.

    Strictly additive. Dark-ship: with no ``token`` or no ``chat_id`` this is a no-op returning
    ``False`` — nothing is sent and no error propagates. A failed send is logged and retried up to
    ``retries`` times, then given up on (the next digest reconciles); it can never break the caller.

    Args:
        token: Bot token, or ``None`` to no-op.
        chat_id: Destination chat id, or ``None`` to no-op.
        text: Message body (HTML unless ``parse_mode`` says otherwise).
        parse_mode: Telegram parse mode for ``text``.
        retries: Extra attempts after the first on failure.
        timeout: Per-request timeout in seconds.

    Returns:
        ``True`` only if Telegram accepted the message (HTTP 200); ``False`` otherwise.
    """
    if not token or not chat_id:
        return False
    url = f"{_API}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            if resp.status_code == 200:
                return True
            _log.warning(
                "telegram_send_non200", extra={"status": resp.status_code, "attempt": attempt}
            )
        except requests.RequestException:
            _log.warning("telegram_send_error", extra={"attempt": attempt})
        if attempt < retries:
            time.sleep(min(2.0, 0.5 * (attempt + 1)))
    return False


def set_my_commands(token: str | None, commands: Iterable[tuple[str, str]]) -> bool:
    """Register the bot's "/" command menu (Bot API ``setMyCommands``). Never raises.

    Telegram persists this server-side, so one successful call makes the menu appear whenever the
    operator types "/" — no per-poll re-registration. Strictly additive: dark-ship no-op with no
    ``token``; a failure is logged and swallowed, and the daemon's next restart retries.

    Args:
        token: Bot token, or ``None`` to no-op.
        commands: ``(name, description)`` pairs (names: lowercase letters/digits/underscores).

    Returns:
        ``True`` if Telegram accepted the registration (HTTP 200); ``False`` otherwise.
    """
    if not token:
        return False
    url = f"{_API}/bot{token}/setMyCommands"
    payload = {"commands": [{"command": name, "description": desc} for name, desc in commands]}
    try:
        resp = requests.post(url, json=payload, timeout=_SEND_TIMEOUT)
        if resp.status_code == 200:
            return True
        _log.warning("telegram_setcommands_non200", extra={"status": resp.status_code})
    except requests.RequestException:
        _log.warning("telegram_setcommands_error")
    return False


def get_updates(
    token: str,
    offset: int | None,
    *,
    long_poll_seconds: int = _LONGPOLL_SECONDS,
) -> list[dict[str, object]]:
    """Long-poll ``getUpdates``; return the updates list (``[]`` on any error — never raises).

    Args:
        token: Bot token.
        offset: Acknowledge everything up to the last processed ``update_id`` (pass ``last + 1``);
            ``None`` on the first poll.
        long_poll_seconds: Server-side wait; the HTTP read waits a little longer so a full-timeout
            poll returns normally instead of tripping the client timeout.

    Returns:
        The list of update objects, or ``[]`` on any transport/parse error.
    """
    url = f"{_API}/bot{token}/getUpdates"
    params: dict[str, int] = {"timeout": long_poll_seconds}
    if offset is not None:
        params["offset"] = offset
    try:
        resp = requests.get(url, params=params, timeout=long_poll_seconds + 10)
        if resp.status_code != 200:
            return []
        body = resp.json()
    except (requests.RequestException, ValueError):
        return []
    if not isinstance(body, dict) or not body.get("ok"):
        return []
    result = body.get("result")
    if not isinstance(result, list):
        return []
    updates: list[dict[str, object]] = []
    for item in result:
        if isinstance(item, dict):
            updates.append(item)
    return updates
