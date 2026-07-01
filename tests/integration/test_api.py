"""Phase 6 step 3: the REST API is a thin reader over the engine, and the gate survives HTTP.

Exercised over real HTTP via FastAPI's TestClient:

* The endpoints return exactly what the engine produced (no recomputation, no second scoring
  path) — read-only verbs only.
* The reliability gate is NOT bypassed at the response layer: a gated calibrator serializes a
  numeric ``probability``; an un-gated one serializes ``probability: null`` plus the
  uncalibrated banner in ``reason``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ipo.calibration.calibrate import load_calibrator
from ipo.calibration.dataset import load_records_from_csv
from ipo.calibration.regime import NiftyRegime
from ipo.core.config import load_config
from ipo.core.interfaces import Calibrator
from ipo.core.types import IPORecord, ListingLabel
from ipo.model.calibrator_placeholder import PlaceholderCalibrator
from ipo.model.scorer import WeightedScorer
from ipo.service.api import create_app
from ipo.service.engine import VerdictEngine

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CSV = _REPO_ROOT / "data" / "backfill" / "mainboard_ipos.csv"
_NIFTY = _REPO_ROOT / "data" / "backfill" / "nifty.csv"
_CAL = _REPO_ROOT / "models" / "calibrator.json"
_REPORT = _REPO_ROOT / "models" / "reliability.json"

pytestmark = pytest.mark.skipif(
    not (_CSV.is_file() and _NIFTY.is_file() and _CAL.is_file()),
    reason="backfill / calibrator artifacts not present",
)


class _ListRepo:
    """Minimal in-memory Repository over a fixed record list (the engine only reads it)."""

    def __init__(self, records: list[IPORecord]) -> None:
        self._records = records

    def upsert(self, record: IPORecord) -> None: ...

    def upsert_many(self, records: list[IPORecord]) -> None: ...

    def get(self, ipo_id: str) -> IPORecord | None:
        return next((r for r in self._records if r.ipo_id == ipo_id), None)

    def list_all(self) -> list[IPORecord]:
        return list(self._records)

    def save_labels(self, labels: list[ListingLabel]) -> None: ...

    def load_labels(self) -> list[ListingLabel]:
        return []


def _client(
    calibrator: Calibrator, *, calibration_report_path: Path | None = None
) -> tuple[TestClient, list[IPORecord]]:
    config = load_config(env="dev", environ={})
    records = load_records_from_csv(_CSV)
    engine = VerdictEngine(
        repository=_ListRepo(records),
        calibrator=calibrator,
        scorer=WeightedScorer(config.feature_weights, config.features),
        config=config,
        regime=NiftyRegime(_NIFTY),
    )
    app = create_app(engine, calibration_report_path=calibration_report_path)
    return TestClient(app), records


def test_health() -> None:
    client, _ = _client(load_calibrator(_CAL))
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ipos_lists_every_verdict() -> None:
    client, records = _client(load_calibrator(_CAL))
    resp = client.get("/ipos")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list) and len(body) == len(records)
    assert {"ipo_id", "verdict", "probability", "reason"} <= set(body[0])


def test_unknown_ipo_returns_404() -> None:
    client, _ = _client(load_calibrator(_CAL))
    assert client.get("/verdict/NONEXISTENT-9999-99-99").status_code == 404
    assert client.get("/ipo/NONEXISTENT-9999-99-99").status_code == 404


def test_ipo_detail_is_enriched_and_consistent() -> None:
    client, _ = _client(load_calibrator(_CAL))
    records = load_records_from_csv(_CSV)
    rec = next(r for r in records if r.qib_sub is not None and r.listing_open is not None)

    resp = client.get(f"/ipo/{rec.ipo_id}")
    assert resp.status_code == 200
    body = resp.json()

    # Enriched shape: record + verdict + point-in-time features + signed contributions.
    assert {"record", "verdict", "features", "contributions"} <= set(body)
    assert body["features"]["ipo_id"] == rec.ipo_id
    assert "qib_sub" in body["features"]

    # Contributions are the scorer's named signed breakdown — non-empty for a scored record.
    contribs = body["contributions"]
    assert isinstance(contribs, dict) and contribs
    assert all(isinstance(v, (int, float)) for v in contribs.values())

    # NO recomputation / no second scoring path: the detail's verdict is byte-for-byte /verdict.
    assert body["verdict"] == client.get(f"/verdict/{rec.ipo_id}").json()


def test_history_pairs_asof_verdict_with_actual_outcome() -> None:
    client, _ = _client(load_calibrator(_CAL))
    records = load_records_from_csv(_CSV)
    listed = [r for r in records if r.listing_open is not None]

    resp = client.get("/history")
    assert resp.status_code == 200
    rows = resp.json()
    # One row per LISTED ipo (an outcome exists only after listing).
    assert isinstance(rows, list) and len(rows) == len(listed)

    r0 = rows[0]
    assert {
        "ipo_id",
        "name",
        "verdict",
        "probability",
        "net_return",
        "gross_return",
        "listed_positive",
    } <= set(r0)

    # The binary label is consistent with the net-of-cost return sign, for every row.
    assert all(row["listed_positive"] == (row["net_return"] > 0) for row in rows)

    # Point-in-time / no second scoring path: the history verdict equals /verdict for that ipo.
    assert r0["verdict"] == client.get(f"/verdict/{r0['ipo_id']}").json()["verdict"]


@pytest.mark.skipif(not _REPORT.is_file(), reason="reliability report not generated")
def test_calibration_serves_heldout_reliability() -> None:
    client, _ = _client(load_calibrator(_CAL), calibration_report_path=_REPORT)
    resp = client.get("/calibration")
    assert resp.status_code == 200
    body = resp.json()

    # Live gate/version from the calibrator; held-out (walk-forward OOS) metrics + bins.
    assert body["gate_passed"] is True
    assert body["version"]
    assert "out-of-sample" in body["source"]
    assert body["n"] > 0 and body["ece"] is not None and body["auc"] is not None
    assert isinstance(body["bins"], list) and body["bins"]
    assert {"mean_predicted", "observed_rate", "count"} <= set(body["bins"][0])


def test_calibration_degrades_without_report() -> None:
    client, _ = _client(load_calibrator(_CAL))  # no report path wired
    body = client.get("/calibration").json()
    # No fabricated curve: empty bins, null metrics, and an explicit source note...
    assert body["source"] == "report not generated"
    assert body["bins"] == [] and body["ece"] is None and body["base_rate"] is None
    # ...but the gate/version still serialize live from the calibrator.
    assert body["gate_passed"] is True and body["version"]


def test_gate_survives_serialization() -> None:
    records = load_records_from_csv(_CSV)
    rec = next(r for r in records if r.qib_sub is not None and r.listing_open is not None)

    gated, _ = _client(load_calibrator(_CAL))
    ungated, _ = _client(PlaceholderCalibrator())

    g = gated.get(f"/verdict/{rec.ipo_id}")
    u = ungated.get(f"/verdict/{rec.ipo_id}")
    assert g.status_code == 200 and u.status_code == 200

    # Gated: a real probability crosses the wire.
    assert g.json()["probability"] is not None

    # Un-gated: the gate is NOT bypassed at the response layer — null + banner.
    assert u.json()["probability"] is None
    assert "UNCALIBRATED" in u.json()["reason"]
