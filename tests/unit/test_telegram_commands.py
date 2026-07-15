"""Inbound commands (v3 V3-3) — owner-only; /status read-only, /login writes ISO, idempotent.

A foreign chat id is silently dropped (no reply, no write) — including /login. /status returns the
renderer's output and touches nothing. /login records today's IST date (ISO) and re-processing
writes the same date.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from ipo.core.constants import IST
from ipo.service.oracle_login import read_oracle_login
from ipo.service.telegram_commands import COMMANDS, handle_update

_AUTH = 42
_STAMP = datetime(2026, 7, 15, 9, 30, tzinfo=IST)


def _update(chat_id: int, text: str) -> dict[str, object]:
    return {"message": {"chat": {"id": chat_id}, "text": text}}


def _handle(tmp_path: Path, chat_id: int, text: str) -> str | None:
    return handle_update(
        _update(chat_id, text),
        authorized_chat_id=_AUTH,
        data_dir=tmp_path,
        now=_STAMP,
        render_status=lambda: "RENDERED",
    )


def test_foreign_chat_is_silently_ignored_including_login(tmp_path: Path) -> None:
    assert _handle(tmp_path, 999, "/status") is None  # no reply
    assert _handle(tmp_path, 999, "/login") is None  # no reply
    assert not (tmp_path / "oracle_login.json").exists()  # a stranger's /login wrote nothing


def test_status_is_read_only_and_uses_the_renderer(tmp_path: Path) -> None:
    assert _handle(tmp_path, _AUTH, "/status") == "RENDERED"
    assert list(tmp_path.iterdir()) == []  # read-only — nothing written


def test_login_writes_the_date_and_roundtrips_iso(tmp_path: Path) -> None:
    reply = _handle(tmp_path, _AUTH, "/login")
    assert reply is not None and "15/07/2026" in reply  # DD/MM/YYYY confirmation
    assert read_oracle_login(tmp_path / "oracle_login.json") == date(2026, 7, 15)
    raw = json.loads((tmp_path / "oracle_login.json").read_text(encoding="utf-8"))
    assert raw["last_login"] == "2026-07-15"  # ISO on disk


def test_login_is_idempotent(tmp_path: Path) -> None:
    _handle(tmp_path, _AUTH, "/login extra args")  # args ignored
    _handle(tmp_path, _AUTH, "/login")
    assert read_oracle_login(tmp_path / "oracle_login.json") == date(2026, 7, 15)


def test_unknown_command_from_owner_gets_help(tmp_path: Path) -> None:
    reply = _handle(tmp_path, _AUTH, "/wat")
    assert reply is not None and "/status" in reply and "/login" in reply


def test_malformed_update_is_ignored(tmp_path: Path) -> None:
    assert _handle(tmp_path, _AUTH, "") is None  # empty text → not a command
    reply = handle_update(
        {}, authorized_chat_id=_AUTH, data_dir=tmp_path, now=_STAMP, render_status=lambda: "X"
    )
    assert reply is None  # no message field → ignored


def test_command_menu_matches_dispatch_and_help(tmp_path: Path) -> None:
    # COMMANDS is the single source: the "/" menu lists exactly what handle_update dispatches, and
    # the fallback help (unknown command) mentions each — so the popup and the dispatch can't drift
    assert {name for name, _ in COMMANDS} == {"status", "login"}
    help_reply = _handle(tmp_path, _AUTH, "/nope")
    assert help_reply is not None
    for name, _desc in COMMANDS:
        assert f"/{name}" in help_reply
