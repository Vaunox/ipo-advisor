"""Telegram client (v3 V3-3) — strictly additive + dark-ship, verified without a network.

``send_telegram`` never raises and returns False on any failure or when unconfigured.
``get_updates`` returns [] on any error. ``requests`` is monkeypatched, so no real HTTP is issued.
"""

from __future__ import annotations

import pytest
import requests

from ipo.service import telegram


def test_send_is_noop_when_unconfigured() -> None:
    # dark-ship: no token / no chat id → no send, no error
    assert telegram.send_telegram(None, "123", "hi") is False
    assert telegram.send_telegram("tok", None, "hi") is False


def test_send_never_raises_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> object:
        raise requests.RequestException("network down")

    monkeypatch.setattr(requests, "post", boom)
    # retries=0 so the test doesn't sleep; the point is it returns False rather than raising
    assert telegram.send_telegram("tok", "123", "hi", retries=0) is False


def test_send_returns_true_on_http_200(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        status_code = 200

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())
    assert telegram.send_telegram("tok", "123", "hi", retries=0) is True


def test_send_returns_false_on_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        status_code = 429

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())
    assert telegram.send_telegram("tok", "123", "hi", retries=0) is False


def test_get_updates_returns_empty_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> object:
        raise requests.RequestException("down")

    monkeypatch.setattr(requests, "get", boom)
    assert telegram.get_updates("tok", None) == []


def test_get_updates_parses_result_list(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"ok": True, "result": [{"update_id": 1}, "junk"]}

    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
    # only well-formed dict updates survive
    assert telegram.get_updates("tok", None) == [{"update_id": 1}]
