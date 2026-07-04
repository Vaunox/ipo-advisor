"""v2 B9: graded regime tiers are annotation-only — MAX |Δprob| = 0.0, each tier populated.

Grading the cold-market flag into normal/soft/cold only changes the caveat text in ``watch``; the
calibrated probability and the verdict type are untouched (``market_regime`` scorer weight is 0).
Proven on the backfill: verdicts computed WITH the regime present (graded tiers active) carry
byte-for-byte the same probability and verdict as verdicts with no regime at all — while both the
soft and cold tiers are actually populated (non-vacuous), so the equality proves something.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ipo.calibration.calibrate import load_calibrator
from ipo.calibration.dataset import load_records_from_csv
from ipo.calibration.regime import NiftyRegime
from ipo.core.config import AppConfig, load_config
from ipo.core.constants import IST
from ipo.core.interfaces import Calibrator
from ipo.core.types import IPORecord, ListingLabel
from ipo.model.scorer import WeightedScorer
from ipo.model.verdict import regime_tier
from ipo.service.engine import VerdictEngine

_ROOT = Path(__file__).resolve().parents[2]
_CSV = _ROOT / "data" / "backfill" / "mainboard_ipos.csv"
_NIFTY = _ROOT / "data" / "backfill" / "nifty.csv"
_CAL = _ROOT / "models" / "calibrator.json"

pytestmark = pytest.mark.skipif(
    not (_CSV.is_file() and _NIFTY.is_file() and _CAL.is_file()),
    reason="backfill / calibrator artifacts not present",
)


class _Repo:
    def __init__(self, records: list[IPORecord]) -> None:
        self._records = records

    def get(self, ipo_id: str) -> IPORecord | None:
        return next((r for r in self._records if r.ipo_id == ipo_id), None)

    def list_all(self) -> list[IPORecord]:
        return list(self._records)

    def upsert(self, record: IPORecord) -> None: ...

    def upsert_many(self, records: list[IPORecord]) -> None: ...

    def save_labels(self, labels: list[ListingLabel]) -> None: ...

    def load_labels(self) -> list[ListingLabel]:
        return []


def _engine(
    records: list[IPORecord],
    config: AppConfig,
    calibrator: Calibrator,
    *,
    regime: NiftyRegime | None,
) -> VerdictEngine:
    return VerdictEngine(
        repository=_Repo(records),
        calibrator=calibrator,
        scorer=WeightedScorer(config.feature_weights, config.features),
        config=config,
        regime=regime,
        clock=lambda: datetime(2026, 7, 4, tzinfo=IST),
    )


def test_graded_tiers_are_annotation_only_and_each_populated() -> None:
    config = load_config(env="dev", environ={})
    records = load_records_from_csv(_CSV)
    calibrator = load_calibrator(_CAL)
    nifty = NiftyRegime(_NIFTY)

    with_regime = _engine(records, config, calibrator, regime=nifty)  # graded tiers active
    no_regime = _engine(records, config, calibrator, regime=None)  # no market_regime → no caveat

    # Byte-equality: the caveat never moves the probability or the verdict type (weight 0).
    max_dprob = 0.0
    for rec in records:
        vr = with_regime.verdict_for(rec)
        vn = no_regime.verdict_for(rec)
        assert vr.verdict == vn.verdict  # the tier never changes the verdict type
        if vr.probability is not None and vn.probability is not None:
            max_dprob = max(max_dprob, abs(vr.probability - vn.probability))
        else:
            assert vr.probability == vn.probability  # both abstain → still equal
    assert max_dprob == 0.0  # MAX |Δprob| = 0.0, exact

    # Non-vacuous: both the soft and cold tiers are actually populated on the sample.
    th = config.verdict_thresholds
    tiers = [regime_tier(with_regime.features_for(r).market_regime, th) for r in records]
    assert tiers.count("soft") >= 1, tiers.count("soft")
    assert tiers.count("cold") >= 1, tiers.count("cold")

    # ...and the graded caveats actually ride in `watch` (≥1 soft, ≥1 cold).
    watches = [with_regime.verdict_for(r).watch for r in records]
    assert any(any("softening market" in w for w in ws) for ws in watches)
    assert any(any("cold market" in w for w in ws) for ws in watches)
