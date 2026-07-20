"""Structured logging output and the secrets boundary."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ipo.core.logging import JsonFormatter, configure_logging, get_logger
from ipo.core.secrets import MissingSecretError, SecretProvider


def test_json_formatter_emits_parseable_line_with_extra() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="ipo.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="ingest complete",
        args=(),
        exc_info=None,
    )
    record.records_ingested = 42
    line = formatter.format(record)
    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "ipo.test"
    assert payload["message"] == "ingest complete"
    assert payload["records_ingested"] == 42
    assert payload["ts"].startswith("2")  # ISO timestamp


def test_configure_logging_is_idempotent() -> None:
    configure_logging("INFO")
    handler_count = len(logging.getLogger().handlers)
    configure_logging("DEBUG")
    assert len(logging.getLogger().handlers) == handler_count
    assert logging.getLogger().level == logging.DEBUG
    assert get_logger("ipo.x").name == "ipo.x"


def test_secret_from_environ() -> None:
    provider = SecretProvider(environ={"PUSH_KEY": "abc123"})
    assert provider.get("PUSH_KEY") == "abc123"
    assert provider.require("PUSH_KEY") == "abc123"


def test_missing_required_secret_raises_without_leaking_value() -> None:
    provider = SecretProvider(environ={})
    with pytest.raises(MissingSecretError) as exc:
        provider.require("PUSH_KEY")
    # The name is referenced; no value can leak because none exists.
    assert "PUSH_KEY" in str(exc.value)


def test_secret_from_file_provider(tmp_path: Path) -> None:
    (tmp_path / "TELEGRAM_TOKEN").write_text("  filetoken  ", encoding="utf-8")
    provider = SecretProvider(environ={}, secrets_dir=tmp_path)
    assert provider.get("TELEGRAM_TOKEN") == "filetoken"


def test_environ_takes_precedence_over_file(tmp_path: Path) -> None:
    (tmp_path / "TELEGRAM_TOKEN").write_text("filetoken", encoding="utf-8")
    provider = SecretProvider(environ={"TELEGRAM_TOKEN": "envtoken"}, secrets_dir=tmp_path)
    assert provider.get("TELEGRAM_TOKEN") == "envtoken"


def test_missing_secret_returns_default() -> None:
    provider = SecretProvider(environ={})
    assert provider.get("ABSENT", default="fallback") == "fallback"


# --- Secrets redaction (structural, at the sink — v3 A/B) ----------------------------------------

# A realistic (fake) JWT, the shape an Upstox access token takes.
_FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"

# A realistic (fake) Telegram bot token: `<bot_id>:<secret>`, the secret 35 URL-safe chars (in the
# {34,45} band the pattern matches). This is the shape logged inside a /bot<token>/ Bot-API URL.
_FAKE_TG = "987654321:ABCdef1234GHIjkl5678MNOpqr9012_-XYZ"


def _record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("ipo.test", logging.INFO, __file__, 1, msg, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_redaction_drops_secret_keyed_values() -> None:
    """A value under a known secret key is dropped whole, regardless of its content."""
    line = JsonFormatter().format(_record("auth ok", token=_FAKE_JWT, api_key="sk-live-1234"))
    payload = json.loads(line)
    assert payload["token"] == "[REDACTED]"
    assert payload["api_key"] == "[REDACTED]"
    assert _FAKE_JWT not in line


def test_redaction_pattern_scrub_catches_secret_under_innocuous_key() -> None:
    """The realistic careless call: the raw token logged under a harmless-looking key.

    The denylist wouldn't catch `detail`; the pattern scrub must — the raw token must not survive
    anywhere in the serialized line.
    """
    line = JsonFormatter().format(_record("context refreshed", detail=f"used {_FAKE_JWT} to fetch"))
    payload = json.loads(line)
    assert _FAKE_JWT not in line
    assert "[REDACTED]" in payload["detail"]


def test_redaction_scrubs_pan_and_message_text() -> None:
    """A PAN-shaped value is scrubbed even when it appears in the free-text message."""
    line = JsonFormatter().format(_record("applicant ABCDE1234F verified"))
    payload = json.loads(line)
    assert "ABCDE1234F" not in line
    assert "[REDACTED]" in payload["message"]


def test_redaction_recurses_into_nested_extras() -> None:
    """A secret nested inside a dict extra is still scrubbed (recursive, not just top-level)."""
    line = JsonFormatter().format(_record("ok", registrar={"name": "KFin", "pan": "ABCDE1234F"}))
    assert "ABCDE1234F" not in line
    assert "[REDACTED]" in line


def test_redaction_scrubs_a_telegram_token_inside_a_bot_url() -> None:
    """A Telegram bot token under an innocuous key — even glued inside a /bot<token>/ URL — is
    redacted, and SURGICALLY (only the token is masked; the URL context survives for debugging).

    This is the exact careless-instrumentation case L5 closes: the app builds
    ``/bot<token>/sendMessage`` URLs (service/telegram.py) and URLs get logged; the key denylist
    wouldn't catch ``url``, so the pattern scrub must.
    """
    url = f"https://api.telegram.org/bot{_FAKE_TG}/sendMessage"
    line = JsonFormatter().format(_record("alert delivered", url=url))
    payload = json.loads(line)
    assert _FAKE_TG not in line  # the raw token survives NOWHERE in the serialized line
    assert "[REDACTED]" in payload["url"]
    assert "api.telegram.org" in payload["url"]  # surgical: host preserved
    assert "/sendMessage" in payload["url"]  # surgical: path preserved


def test_redaction_leaves_innocent_colon_text_untouched() -> None:
    """The false-positive guard (load-bearing): the Telegram pattern must NOT eat ordinary
    colon-separated log text — a local URL with a port, an ISO timestamp, a ratio, and a key:value
    pair all survive verbatim. A redaction pattern that redacts innocent text is its own bug.
    """
    innocent = (
        "engine http://127.0.0.1:58145/health up at 2026-07-20T13:02:41 ratio 1000000:1 count:42"
    )
    line = JsonFormatter().format(_record(innocent))
    payload = json.loads(line)
    assert payload["message"] == innocent  # byte-identical — nothing matched, nothing masked
    assert "[REDACTED]" not in line


def test_every_configured_sink_redacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Structural guarantee: configure_logging wires redaction onto EVERY sink.

    The stderr and rotating-file handlers redact via their formatter (redaction lives in the
    formatter each runs, so a new log call can't bypass it); the debug-console ring buffer (V3-16)
    redacts at store time via ``redacted_payload``. No sink the file or the console can read is left
    un-redacted.
    """
    import ipo.core.logging as logging_module

    root = logging.getLogger()
    saved = root.handlers[:]
    saved_ring = logging_module._RING
    monkeypatch.setattr(logging_module, "_CONFIGURED", False)
    try:
        configure_logging("INFO", file_path=tmp_path / "logs" / "engine.log")
        handlers = root.handlers
        assert len(handlers) == 3  # stderr + ring buffer + rotating file
        text_sinks = [h for h in handlers if not isinstance(h, logging_module.RingBufferHandler)]
        assert len(text_sinks) == 2  # stderr + rotating each carry a redacting formatter
        for handler in text_sinks:
            assert isinstance(
                handler.formatter,
                (JsonFormatter, logging_module._RedactingTextFormatter),
            )
        rings = [h for h in handlers if isinstance(h, logging_module.RingBufferHandler)]
        assert len(rings) == 1  # the console's live-tail sink
        rings[0].emit(_record("x", token="s3cr3t"))  # redacts at store time, not via a formatter
        assert rings[0].entries()[-1]["token"] == "[REDACTED]"
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers = saved
        logging_module._RING = saved_ring
