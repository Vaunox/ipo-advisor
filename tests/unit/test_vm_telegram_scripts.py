"""VM Telegram scripts (v3 V3-3) — dark-ship, single-writer, offset ack, digest vs alert.

Each script is inert with no creds (the gate has none): the daemon never enters the poll loop, the
digest/alert-check send nothing (a raise-on-call stub proves it). Configured: the daemon advances
the getUpdates offset + touches bot.marker; the digest sends unconditionally and writes nothing;
the alert-check sends only on a transition and writes only alert_state.json.
"""

from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

from ipo.core.constants import IST
from ipo.data.ingest.state import IngestStateStore
from ipo.service.oracle_login import record_oracle_login

_NOW = datetime(2026, 7, 15, 18, 0, tzinfo=IST)


def _load(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _healthy(data: Path) -> None:
    """A fully-healthy data dir; markers pinned to _NOW so freshness is wall-clock-independent."""
    IngestStateStore(data / "ingest_state.json").record_success(_NOW - timedelta(minutes=10))
    ctx = data / "context" / "ipo_context.json"
    ctx.parent.mkdir(parents=True, exist_ok=True)
    ctx.write_text(
        f'{{"refreshed_at": "{(_NOW - timedelta(hours=3)).isoformat()}"}}', encoding="utf-8"
    )
    record_oracle_login(data / "oracle_login.json", now=_NOW - timedelta(days=2))
    for marker in ("keepalive.marker", "bot.marker"):
        path = data / marker
        path.write_text("", encoding="utf-8")
        os.utime(path, (_NOW.timestamp(), _NOW.timestamp()))  # pin mtime → deterministic freshness


def _clear_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)


def _set_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")


def _boom(*_args: object, **_kwargs: object) -> object:
    raise AssertionError("dark-ship must make no network call")


# --- dark-ship: no creds → inert no-op (the CI gate has no telegram.env) ------------------------


def test_daemon_darkships_without_creds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _load("vm_telegram_bot")
    _clear_creds(monkeypatch)
    monkeypatch.setattr(bot, "get_updates", _boom)  # would raise if the loop ran
    bot.run_daemon(tmp_path, poll_limit=3)  # returns without polling → no spin


def test_digest_darkships_without_creds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    digest = _load("vm_telegram_digest")
    _clear_creds(monkeypatch)
    monkeypatch.setattr(digest, "send_telegram", _boom)
    assert digest.run_digest(tmp_path) is False  # no send, no raise


def test_alert_check_darkships_without_creds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ac = _load("vm_alert_check")
    _clear_creds(monkeypatch)
    monkeypatch.setattr(ac, "send_telegram", _boom)
    assert ac.run_alert_check(tmp_path) == []
    assert not (tmp_path / "alert_state.json").exists()  # wrote nothing either


# --- daemon: offset ack + marker touch + owner-only reply --------------------------------------


def test_daemon_advances_offset_touches_marker_and_replies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = _load("vm_telegram_bot")
    updates = [
        {"update_id": 10, "message": {"chat": {"id": 42}, "text": "/hi"}},  # owner unknown → help
        {"update_id": 11, "message": {"chat": {"id": 999}, "text": "/status"}},  # stranger → drop
    ]
    sent: list[str] = []

    def _send(token: object, chat: object, text: str, **_k: object) -> bool:
        sent.append(text)
        return True

    monkeypatch.setattr(bot, "get_updates", lambda *a, **k: updates)
    monkeypatch.setattr(bot, "send_telegram", _send)
    next_offset = bot.poll_once("tok", 42, None, data_dir=tmp_path)
    assert next_offset == 12  # acked past update_id 11
    assert (tmp_path / "bot.marker").is_file()  # proof-of-life touched
    assert len(sent) == 1  # only the owner's message replied; the stranger was ignored


# --- digest: sends unconditionally, writes nothing ---------------------------------------------


def test_digest_sends_and_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    digest = _load("vm_telegram_digest")
    _set_creds(monkeypatch)
    _healthy(tmp_path)
    sent: list[str] = []

    def _send(token: object, chat: object, text: str, **_k: object) -> bool:
        sent.append(text)
        return True

    monkeypatch.setattr(digest, "send_telegram", _send)
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    assert digest.run_digest(tmp_path, now=_NOW, probe=lambda _: True) is True
    after = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after  # the digest writes NOTHING (single-writer: owns no file)
    assert "IPO VM — OK" in sent[0]


# --- alert-check: fires on transition, writes only alert_state.json -----------------------------


def test_alert_check_fires_on_transition_and_owns_only_alert_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ac = _load("vm_alert_check")
    _set_creds(monkeypatch)
    _healthy(tmp_path)
    sent: list[str] = []

    def _send(token: object, chat: object, text: str, **_k: object) -> bool:
        sent.append(text)
        return True

    monkeypatch.setattr(ac, "send_telegram", _send)
    before = {p.name for p in tmp_path.rglob("*") if p.is_file()}
    keys = ac.run_alert_check(tmp_path, now=_NOW, probe=lambda _: False)  # read-API down
    assert "Read-API" in keys and any("Read-API" in s for s in sent)
    after = {p.name for p in tmp_path.rglob("*") if p.is_file()}
    assert after - before == {"alert_state.json"}  # the ONLY new/owned write
    sent.clear()
    ac.run_alert_check(tmp_path, now=_NOW, probe=lambda _: False)  # same state → suppressed
    assert sent == []
