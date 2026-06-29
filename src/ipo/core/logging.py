"""Structured logging, configured once (Ground Rule 8).

Emits JSON lines with IST timestamps, the level, the logger name, the message, and
any structured ``extra`` fields. Configuration is idempotent (safe to call more
than once). Secrets are never passed here and never logged.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from ipo.core.constants import IST

# Standard LogRecord attributes we do not want to duplicate inside ``extra``.
_RESERVED = frozenset(
    logging.makeLogRecord({}).__dict__.keys() | {"message", "asctime", "taskName"}
)

_CONFIGURED = False


class JsonFormatter(logging.Formatter):
    """Render a ``LogRecord`` as a single JSON line with an IST timestamp."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize one record to a JSON line, promoting structured extras."""
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=IST).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # Promote any structured fields passed via logger.x(..., extra={...}).
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Configure the root logger once. Subsequent calls only adjust the level.

    Args:
        level: Minimum level name (``DEBUG``..``CRITICAL``).
        json_output: Emit JSON lines (True) or a plain human format (False).
    """
    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(level.upper())
    if _CONFIGURED:
        return

    handler = logging.StreamHandler()
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.handlers = [handler]
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger (configure the root once at startup first)."""
    return logging.getLogger(name)
