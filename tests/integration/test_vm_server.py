"""VM read-API server (v3 V3-1c) — the read plane the app fetches records + context from.

Asserts the two structural guarantees plus honest degradation: it is GET-only (no mutation route),
it never imports the model (data-only — the VM cannot score), each store comes in a
``{refreshed_at, data}`` envelope, and a missing context cache degrades to empty, not an error.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from ipo.core.constants import IST
from ipo.core.types import IPORecord, Segment
from ipo.data.ingest.state import IngestStateStore
from ipo.data.store.repository import ParquetRepository
from ipo.vm.server import _RATE_LIMIT_REQUESTS, _FixedWindowLimiter, create_vm_app


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


def test_records_route_nulls_refreshed_at_on_corrupt_store(tmp_path: Path) -> None:
    """A torn records store must not 500, nor present a stale success time as current."""
    _seed(tmp_path)  # valid store + last_success set...
    (tmp_path / "ipo_records.parquet").write_bytes(b"not a parquet file")  # ...then corrupt it

    resp = TestClient(create_vm_app(tmp_path)).get("/records")

    assert resp.status_code == 200  # degraded, not a permanent per-request outage
    body = resp.json()
    assert body["records"] == []  # honest empty
    assert body["refreshed_at"] is None  # the corrupt read null's freshness — like /context


def test_records_route_keeps_refreshed_at_when_genuinely_empty_but_fresh(tmp_path: Path) -> None:
    """M2 must not over-null: a real ingest that found no open IPOs is honestly fresh + empty.

    ``_flush_records`` skips writing an empty table, so a genuine empty-but-fresh state is "no
    records file + last_success set" — indistinguishable on the wire from corruption unless the flag
    keeps them apart. Here the flag is False, so ``refreshed_at`` survives.
    """
    IngestStateStore(tmp_path / "ingest_state.json").record_success(
        datetime(2026, 7, 14, 9, 0, tzinfo=IST)
    )

    body = TestClient(create_vm_app(tmp_path)).get("/records").json()

    assert body["records"] == []
    assert body["refreshed_at"].startswith("2026-07-14T09:00:00")  # real freshness kept, not nulled


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


def test_normal_app_polling_is_never_rate_limited(tmp_path: Path) -> None:
    """The real traffic shape must pass untouched: 2 calls per user per ~30-min ingest cycle.

    Simulates a whole CGNAT'd carrier — 20 users sharing one public IP, each pulling /records +
    /context in the same cycle — because that shared IP is the realistic worst case, not one user.
    """
    _seed(tmp_path)
    client = TestClient(create_vm_app(tmp_path))
    for _ in range(20):
        assert client.get("/records").status_code == 200
        assert client.get("/context").status_code == 200


def test_burst_beyond_the_limit_is_rejected_with_retry_after(tmp_path: Path) -> None:
    _seed(tmp_path)
    client = TestClient(create_vm_app(tmp_path))
    codes = [client.get("/health").status_code for _ in range(_RATE_LIMIT_REQUESTS + 5)]
    assert codes[:_RATE_LIMIT_REQUESTS] == [200] * _RATE_LIMIT_REQUESTS  # the allowance passes
    assert set(codes[_RATE_LIMIT_REQUESTS:]) == {429}  # everything past it is refused
    refused = client.get("/health")
    assert int(refused.headers["Retry-After"]) >= 1  # tells the caller when to come back


def test_rate_limited_response_still_carries_cors_headers(tmp_path: Path) -> None:
    """CORS must wrap the limiter, or a browser sees an opaque CORS error instead of a clean 429."""
    client = TestClient(create_vm_app(tmp_path))
    for _ in range(_RATE_LIMIT_REQUESTS):
        client.get("/health")
    refused = client.get("/health", headers={"Origin": "https://ipoadvisor.in"})
    assert refused.status_code == 429
    assert refused.headers["access-control-allow-origin"] == "*"


def test_limiter_memory_stays_bounded_under_many_distinct_sources() -> None:
    """An unbounded {ip: state} dict is itself a way to kill a 1 GB box — prove the cap holds."""
    limiter = _FixedWindowLimiter(limit=60, window=60.0, max_tracked=100)
    for i in range(5_000):  # 5k distinct "IPs", far past the cap
        limiter.check(f"10.0.{i // 256}.{i % 256}", now=1_000.0)
    assert len(limiter._windows) <= 100


def test_window_resets_so_a_limited_caller_recovers() -> None:
    limiter = _FixedWindowLimiter(limit=2, window=60.0, max_tracked=100)
    assert limiter.check("1.2.3.4", now=0.0) == (None, False)
    assert limiter.check("1.2.3.4", now=1.0) == (None, False)
    retry_after, first = limiter.check("1.2.3.4", now=2.0)
    assert retry_after is not None and first is True  # third call in-window is refused, and logged
    assert limiter.check("1.2.3.4", now=61.0) == (None, False)  # next window: allowed again


def test_vm_server_never_imports_the_model() -> None:
    """The VM serves inputs and cannot score — importing it must not pull the model/feature code.

    Runs in a subprocess because this process has already imported the scoring modules via other
    tests, so its own ``sys.modules`` cannot answer the question. ``PYTHONPATH`` must be passed
    explicitly: pytest puts ``src`` on the path via ``[tool.pytest.ini_options] pythonpath``, and
    that does NOT reach a child process — without it the probe dies on ``ModuleNotFoundError`` and
    the assertion below reports an empty leak-list as though the boundary had been breached. Same
    pattern as the sibling closure guard in ``tests/unit/test_ipo_context.py``.
    """
    src = Path(__file__).resolve().parents[2] / "src"
    code = (
        "import sys, ipo.vm.server;"
        "bad=[m for m in sys.modules if m.split('.')[:2]==['ipo','model']"
        " or m.startswith('ipo.features') or m=='ipo.service.engine'];"
        "print(','.join(sorted(bad)));"
        "sys.exit(1 if bad else 0)"
    )
    env = {**os.environ, "PYTHONPATH": str(src) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    # stderr is included so a probe that never RAN is distinguishable from a real breach.
    assert result.returncode == 0, (
        f"VM server pulled scoring modules: {result.stdout.strip()!r} (stderr: "
        f"{result.stderr.strip()!r})"
    )
