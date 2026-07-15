"""Oracle-login store (v3 V3-3) — absent reads as a clean None sentinel; writes round-trip as ISO.

The countdown treats "never recorded" as first-class, so the read must never throw. A /login write
must leave oracle_login.json machine-parseable (ISO last_login) so the day-count can re-parse it
— the do-not-touch guard: storage stays ISO, rendering converts to DD/MM/YYYY on the way out.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from ipo.core.constants import IST
from ipo.service.oracle_login import read_oracle_login, record_oracle_login


def test_absent_file_reads_as_none_sentinel(tmp_path: Path) -> None:
    assert read_oracle_login(tmp_path / "nope.json") is None


def test_corrupt_file_reads_as_none(tmp_path: Path) -> None:
    bad = tmp_path / "oracle_login.json"
    bad.write_text("{ truncated", encoding="utf-8")
    assert read_oracle_login(bad) is None


def test_record_then_read_roundtrips_the_date(tmp_path: Path) -> None:
    path = tmp_path / "oracle_login.json"
    recorded = record_oracle_login(path, now=datetime(2026, 7, 15, 9, 30, tzinfo=IST))
    assert recorded == date(2026, 7, 15)
    assert read_oracle_login(path) == date(2026, 7, 15)


def test_stored_last_login_stays_iso(tmp_path: Path) -> None:
    path = tmp_path / "oracle_login.json"
    record_oracle_login(path, now=datetime(2026, 7, 15, 9, 30, tzinfo=IST))
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["last_login"] == "2026-07-15"  # ISO date, not DD/MM/YYYY
    assert raw["recorded_at"].startswith("2026-07-15T")  # full ISO + offset
