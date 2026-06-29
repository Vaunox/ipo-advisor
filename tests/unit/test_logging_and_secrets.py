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
