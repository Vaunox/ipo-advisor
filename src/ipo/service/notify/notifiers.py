"""Notifier implementations + factory (Layer 5) — advisory alerts, never actions.

A notification informs the operator that a verdict crossed into APPLY; it never places an
order (Inviolable Rule 6). Channels are config-selected: ``none`` (off), ``log`` (a structured
log line — always available), and ``push`` (delivered through an injected transport, e.g. a
webhook POST). Telegram/email are deferred behind config until their transports are wired, and
raise rather than silently drop, so a misconfiguration fails loudly.
"""

from __future__ import annotations

from collections.abc import Callable

from ipo.core.config import AppConfig
from ipo.core.interfaces import Notifier
from ipo.core.logging import get_logger
from ipo.core.types import Verdict


class NullNotifier:
    """``channel=none``: deliberately does nothing — notifications are off at the sink."""

    def notify(self, verdict: Verdict, *, message: str) -> None:
        """Drop the alert (no-op)."""
        return None


class LogNotifier:
    """``channel=log``: emits the advisory alert as one structured log line."""

    def __init__(self) -> None:
        """Bind the notify logger."""
        self._log = get_logger("ipo.notify")

    def notify(self, verdict: Verdict, *, message: str) -> None:
        """Log the alert with its grounded fields (advisory only)."""
        self._log.info(
            "ipo_alert",
            extra={
                "ipo_id": verdict.ipo_id,
                "verdict": verdict.verdict.value,
                "probability": verdict.probability,
                "message": message,
            },
        )


class PushNotifier:
    """``channel=push``: delivers the alert through an injected transport (e.g. a webhook)."""

    def __init__(self, transport: Callable[[str], None]) -> None:
        """Bind the message transport (the caller wires the actual sender)."""
        self._send = transport

    def notify(self, verdict: Verdict, *, message: str) -> None:
        """Push the alert message through the transport."""
        self._send(message)


def build_notifier(
    config: AppConfig, *, push_transport: Callable[[str], None] | None = None
) -> Notifier:
    """Return the notifier for the configured channel (``none`` / ``log`` / ``push``).

    Telegram/email are deferred behind config (their transports are not wired yet) and raise
    ``NotImplementedError`` so a misconfiguration fails loudly rather than silently dropping.
    """
    channel = config.notify.channel
    if channel == "none":
        return NullNotifier()
    if channel == "log":
        return LogNotifier()
    if channel == "push":
        if push_transport is None:
            raise ValueError("notify channel 'push' requires a transport (wire the sender)")
        return PushNotifier(push_transport)
    raise NotImplementedError(f"notify channel '{channel}' is not wired yet (Telegram/email)")
