"""VM read-API server (v3 V3-1c) — the read plane the app fetches records + context from.

Asserts the two structural guarantees plus honest degradation: it is GET-only (no mutation route),
it never imports the model (data-only — the VM cannot score), each store comes in a
``{refreshed_at, data}`` envelope, and a missing context cache degrades to empty, not an error.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from ipo.core.constants import IST
from ipo.core.types import IPORecord, Segment
from ipo.data.ingest.state import IngestStateStore
from ipo.data.store.repository import ParquetRepository
from ipo.vm.server import create_vm_app


def _seed(data_dir: Path) -> None:
    repo = ParquetRepository(data_dir)
    repo.upsert(
        IPORecord(
            ipo_id="acme",
            name="Acme Ltd",
            segment=Segment("mainboard"),
            price_band_low=100.0,
            price_band_high=110.0,
            open_date=date(2026, 7, 1),
            close_date=date(2026, 7, 3),
            qib_sub=3.0,
            captured_at=datetime(2026, 7, 3, 17, 0),
        )
    )
    IngestStateStore(data_dir / "ingest_state.json").record_success(
        datetime(2026, 7, 14, 9, 0, tzinfo=IST)
    )
    ctx = data_dir / "context" / "ipo_context.json"
    ctx.parent.mkdir(parents=True, exist_ok=True)
    payload = {"refreshed_at": "2026-07-14T09:00:00+05:30", "ipos": {"ACME": {"isin": "INE0X"}}}
    ctx.write_text(json.dumps(payload), encoding="utf-8")


def test_health(tmp_path: Path) -> None:
    client = TestClient(create_vm_app(tmp_path))
    assert client.get("/health").json() == {"status": "ok"}


def test_records_envelope_carries_freshness_and_records(tmp_path: Path) -> None:
    _seed(tmp_path)
    body = TestClient(create_vm_app(tmp_path)).get("/records").json()
    assert body["refreshed_at"].startswith("2026-07-14T09:00:00")  # freshness travels with the data
    assert [r["ipo_id"] for r in body["records"]] == ["acme"]


def test_context_served_verbatim(tmp_path: Path) -> None:
    _seed(tmp_path)
    body = TestClient(create_vm_app(tmp_path)).get("/context").json()
    assert body["refreshed_at"] == "2026-07-14T09:00:00+05:30"
    assert body["ipos"]["ACME"]["isin"] == "INE0X"


def test_missing_context_degrades_honestly(tmp_path: Path) -> None:
    # No cache written → empty envelope, not a 500 (the app's field_state reads it the same way).
    body = TestClient(create_vm_app(tmp_path)).get("/context").json()
    assert body == {"refreshed_at": None, "ipos": {}}


def test_api_is_structurally_read_only(tmp_path: Path) -> None:
    """No route allows a mutating verb — the app can read the VM but never make it act."""
    app = create_vm_app(tmp_path)
    for route in app.routes:
        methods: set[str] = getattr(route, "methods", set())  # APIRoutes have .methods
        path = getattr(route, "path", "?")
        assert set(methods) <= {"GET", "HEAD", "OPTIONS"}, f"{path} allows {methods}"
    # And functionally: a write is rejected, not silently accepted.
    assert TestClient(app).post("/records").status_code == 405


def test_vm_server_never_imports_the_model() -> None:
    """The VM serves inputs and cannot score — importing it must not pull the model/feature code."""
    code = (
        "import sys, ipo.vm.server;"
        "bad=[m for m in sys.modules if m.split('.')[:2]==['ipo','model']"
        " or m.startswith('ipo.features') or m=='ipo.service.engine'];"
        "print(','.join(sorted(bad)));"
        "sys.exit(1 if bad else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, f"VM server pulled scoring modules: {result.stdout.strip()}"
