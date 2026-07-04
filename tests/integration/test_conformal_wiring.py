"""B8 Idea 1 wiring: the conformal band is purely additive — MAX |Δprob| = 0.0 (non-vacuous).

Builds two live engines over the real backfill + gated calibrator — one with the conformal bands
wired, one without — and asserts every calibrated probability and verdict is byte-for-byte
identical (the band is downstream display context, never a scoring input), while the wired engine
*does* attach bands (so the proof is not vacuous).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ipo.calibration.calibrate import load_calibrator
from ipo.calibration.conformal import ConformalBands, load_conformal
from ipo.calibration.dataset import load_records_from_csv
from ipo.calibration.regime import NiftyRegime, VixSeries
from ipo.core.config import AppConfig, load_config
from ipo.core.types import IPORecord, ListingLabel
from ipo.model.scorer import WeightedScorer
from ipo.service.engine import VerdictEngine

_ROOT = Path(__file__).resolve().parents[2]
_CSV = _ROOT / "data" / "backfill" / "mainboard_ipos.csv"
_NIFTY = _ROOT / "data" / "backfill" / "nifty.csv"
_VIX = _ROOT / "data" / "backfill" / "vix.csv"
_CAL = _ROOT / "models" / "calibrator.json"
_CONF = _ROOT / "models" / "conformal.json"

pytestmark = pytest.mark.skipif(
    not all(p.is_file() for p in (_CSV, _NIFTY, _VIX, _CAL, _CONF)),
    reason="backfill / calibrator / conformal artifacts not present",
)


class _Repo:
    """Minimal in-memory Repository (the engine only reads it)."""

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


def _engine(
    records: list[IPORecord], config: AppConfig, *, conformal: ConformalBands | None
) -> VerdictEngine:
    rc = config.features.regime
    return VerdictEngine(
        repository=_Repo(records),
        calibrator=load_calibrator(_CAL),
        scorer=WeightedScorer(config.feature_weights, config.features),
        config=config,
        regime=NiftyRegime(_NIFTY),
        vix=VixSeries(_VIX, reference=rc.vix_reference, scale=rc.vix_scale),
        conformal=conformal,
    )


def test_conformal_band_is_additive_and_changes_no_probability() -> None:
    config = load_config(env="dev", environ={})
    records = load_records_from_csv(_CSV)
    with_band = _engine(records, config, conformal=load_conformal(_CONF))
    without = _engine(records, config, conformal=None)

    max_delta = 0.0
    banded = 0
    for record in records:
        dw = with_band.detail(record)
        dn = without.detail(record)
        assert dw.verdict.verdict == dn.verdict.verdict  # same verdict
        assert (dw.verdict.probability is None) == (dn.verdict.probability is None)
        if dw.verdict.probability is not None and dn.verdict.probability is not None:
            max_delta = max(max_delta, abs(dw.verdict.probability - dn.verdict.probability))

        assert dn.probability_band is None  # no band without the conformal model
        if dw.probability_band is not None:
            banded += 1
            lo, hi = dw.probability_band
            p = dw.verdict.probability
            assert p is not None and 0.0 <= lo <= p <= hi <= 1.0  # band brackets the point prob
        else:
            assert dw.verdict.probability is None  # band absent only when there is no probability

    assert (
        max_delta == 0.0
    )  # MAX |Δprob| = 0.0 — the calibrated probability is byte-for-byte intact
    assert banded > 0  # non-vacuous: the wired engine actually produced bands
