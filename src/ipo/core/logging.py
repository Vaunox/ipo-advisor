"""Structured logging, configured once (Ground Rule 8).

Emits JSON lines with IST timestamps, the level, the logger name, the message, and any structured
``extra`` fields. Configuration is idempotent (safe to call more than once).

**Secrets guarantee (structural, at the sink).** Redaction happens in the formatter — the serializer
every handler runs to produce its output — not at the call site. So it is *impossible* to bypass by
writing a new log call that forgets to sanitize: any record, whatever key it used, is scrubbed on
the way out. A value under a known secret key (``token``/``authorization``/``pan``/…) is dropped
whole; a secret smuggled under an innocuous key (``extra={"detail": "<the raw token>"}``) is caught
by the pattern scrub (JWT / Bearer / PAN shapes). Covers the message, every extra (recursively), and
exception text. Verified in tests/unit/test_logging_and_secrets.py.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import deque
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from ipo.core.constants import IST

# Standard LogRecord attributes we do not want to duplicate inside ``extra``.
_RESERVED = frozenset(
    logging.makeLogRecord({}).__dict__.keys() | {"message", "asctime", "taskName"}
)

_CONFIGURED = False

# Third-party loggers that spam DEBUG/INFO (connection pools, the event loop) — pinned to WARNING so
# they never drown out our own events in the file (or the debug console once it lands).
_NOISY_LOGGERS = ("urllib3", "asyncio", "httpcore", "httpx")

# --- Secrets redaction (structural — applied in the formatter, see module docstring) -------------
# Keys whose VALUE is a secret regardless of content → dropped whole.
_SECRET_KEYS = frozenset(
    {
        "token",
        "access_token",
        "refresh_token",
        "upstox_token",
        "authorization",
        "auth",
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "x-api-key",
        "cookie",
        "set-cookie",
        "pan",
    }
)
# Value SHAPES that are secret whatever key they arrive under (the careless-instrumentation case).
_SECRET_PATTERNS = (
    re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"),  # JWT (Upstox)
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),  # "Bearer <token>"
    re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),  # Indian PAN
)
_REDACTED = "[REDACTED]"


def _scrub_text(text: str) -> str:
    """Replace every secret-shaped substring with ``[REDACTED]``."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


def _scrub(key: str, value: Any) -> Any:
    """Redact a single (key, value): drop secret-keyed values, pattern-scrub strings, recurse."""
    if key.lower() in _SECRET_KEYS:
        return _REDACTED
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, dict):
        return {k: _scrub(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(key, v) for v in value]
    return value


# One shared Formatter instance, used only for its ``formatException`` (turning exc_info into text).
_EXC_FMT = logging.Formatter()


def redacted_payload(record: logging.LogRecord) -> dict[str, Any]:
    """Build the ``{ts, level, logger, message, …extras}`` dict for a record, redacted at the sink.

    The ONE place the secrets guarantee is enforced: every value (message, each promoted extra, the
    exception text) passes through ``_scrub``. Shared by :class:`JsonFormatter` (json-dumped to the
    file/stderr) and :class:`RingBufferHandler` (stored for the debug console) — so **both** paths
    the console can read are redacted by construction; no secret reaches either.
    """
    payload: dict[str, Any] = {
        "ts": datetime.fromtimestamp(record.created, tz=IST).isoformat(),
        "level": record.levelname,
        "logger": record.name,
        "message": record.getMessage(),
    }
    if record.exc_info:
        payload["exc_info"] = _EXC_FMT.formatException(record.exc_info)
    # Promote any structured fields passed via logger.x(..., extra={...}).
    for key, value in record.__dict__.items():
        if key not in _RESERVED and not key.startswith("_"):
            payload[key] = value
    # Redact on the way out — the one place no log call can skip (secrets guarantee).
    return {key: _scrub(key, value) for key, value in payload.items()}


class JsonFormatter(logging.Formatter):
    """Render a ``LogRecord`` as a single JSON line with an IST timestamp, redacted at the sink."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize a record to a redacted JSON line (promotes extras via ``redacted_payload``)."""
        return json.dumps(redacted_payload(record), default=str, ensure_ascii=False)


class RingBufferHandler(logging.Handler):
    """In-memory ring of recent redacted log payloads — the debug console's live tail (V3-16).

    Bounded (a ``deque`` with a fixed ``maxlen``, so memory stays constant — old entries evicted,
    never grown), thread-safe (scheduler, stdin-refresh, and API threads all log), and **redacted at
    store time** via the same ``redacted_payload`` the file sink uses — so the console reading this
    buffer can never read back a token/PAN/auth-header. Each entry carries a monotonic ``seq`` so a
    poller asks only for what's ``since`` its last seq.
    """

    def __init__(self, capacity: int = 2000) -> None:
        """Hold at most ``capacity`` recent redacted payloads (FIFO eviction)."""
        super().__init__()
        self._buf: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._seq = 0

    def emit(self, record: logging.LogRecord) -> None:
        """Store the redacted payload with a monotonic seq; never raises (a sink must not)."""
        try:
            payload = redacted_payload(record)
        except Exception:  # noqa: BLE001 — a logging sink must never propagate to its caller
            self.handleError(record)
            return
        with self._lock:
            self._seq += 1
            payload["seq"] = self._seq
            self._buf.append(payload)

    def entries(self, *, since: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        """Buffered payloads with ``seq > since`` (oldest→newest), newest ``limit`` kept."""
        with self._lock:
            items = [e for e in self._buf if e["seq"] > since]
        return items[-limit:]

    def latest_seq(self) -> int:
        """Highest seq emitted so far (0 = nothing logged) — the client's next ``since``."""
        with self._lock:
            return self._seq


_RING: RingBufferHandler | None = None


def get_ring_buffer() -> RingBufferHandler | None:
    """The process-wide ring the console reads, or ``None`` before ``configure_logging``."""
    return _RING


def _expire_old_logs(log_dir: Path, *, max_age_days: int = 14) -> None:
    """Delete rotated ``engine.log.*`` older than ``max_age_days`` — a time bound atop the size cap.

    Best-effort: a file we can't stat/unlink is left for the next run, never raised.
    """
    cutoff = time.time() - max_age_days * 86_400
    try:
        rotated = list(log_dir.glob("engine.log.*"))
    except OSError:
        return
    for path in rotated:
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


class _RedactingTextFormatter(logging.Formatter):
    """Human-readable formatter (dev only) that still redacts secrets from its output line."""

    def format(self, record: logging.LogRecord) -> str:
        return _scrub_text(super().format(record))


def configure_logging(
    level: str = "INFO",
    *,
    json_output: bool = True,
    file_path: Path | None = None,
    stderr_level: str = "WARNING",
) -> None:
    """Configure the root logger once. Subsequent calls only adjust the level.

    Args:
        level: Minimum level name (``DEBUG``..``CRITICAL``) — the floor for the file sink.
        json_output: Emit JSON lines (True) or a redacting human format (False).
        file_path: When given (the engine runner), also write to a size-capped rotating file there
            (durable, greppable detail). stderr is then held at ``stderr_level`` so the desktop
            shell's console isn't flooded — the file carries the full detail. When absent (batch
            scripts), a single stderr handler carries everything at ``level``.
        stderr_level: The stderr floor when a file sink exists (default WARNING).
    """
    global _CONFIGURED, _RING
    root = logging.getLogger()
    root.setLevel(level.upper())
    if _CONFIGURED:
        return

    def _formatter() -> logging.Formatter:
        if json_output:
            return JsonFormatter()
        return _RedactingTextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    handlers: list[logging.Handler] = []
    stderr = logging.StreamHandler()
    stderr.setFormatter(_formatter())
    stderr.setLevel((stderr_level if file_path is not None else level).upper())
    handlers.append(stderr)

    # The debug console's live tail (V3-16): a redacted, bounded in-memory ring the read-API serves.
    # Always present so GET /logs works wherever the engine runs; formats nothing (stores dicts).
    _RING = RingBufferHandler()
    _RING.setLevel(level.upper())
    handlers.append(_RING)

    if file_path is not None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        _expire_old_logs(file_path.parent)  # V3-16: time bound (~14d) atop the 25 MB size cap
        # 5 MB x 5 files = 25 MB hard ceiling, forever (v3 A/B). The debug console (V3-16) reads the
        # ring above for the live tail and these rotated files for scroll-back history.
        rotating = RotatingFileHandler(
            file_path, maxBytes=5 * 1024 * 1024, backupCount=4, encoding="utf-8"
        )
        rotating.setFormatter(_formatter())
        rotating.setLevel("INFO")  # INFO+ floor to disk (DEBUG, if ever added, stays ring-only)
        handlers.append(rotating)

    root.handlers = handlers
    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger (configure the root once at startup first)."""
    return logging.getLogger(name)
