"""Phase 6 step 2: the live VerdictEngine composes the pipeline without breaking invariants.

Two guarantees, mirroring step 1 but end-to-end through the engine:

* **Regime is not a back-door into the score.** The probability the engine emits (regime wired
  in via ``market_regime_of``, weight 0) equals the official-only probability for every IPO —
  asserted as exact equality, not a tolerance. The cold flag still fires (annotation only).
* **The probability stays gated on the reliability gate.** An un-gated calibrator yields a
  verdict with NO probability and the uncalibrated banner; the gated calibrator yields one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ipo.calibration.calibrate import load_calibrator
from ipo.calibration.dataset import load_records_from_csv
from ipo.calibration.regime import NiftyRegime
from ipo.core.config import load_config
from ipo.core.types import IPORecord, ListingLabel
from ipo.features.build import build_features
from ipo.model.calibrator_placeholder import PlaceholderCalibrator
from ipo.model.scorer import WeightedScorer
from ipo.model.verdict import evaluate
from ipo.service.engine import VerdictEngine

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CSV = _REPO_ROOT / "data" / "backfill" / "mainboard_ipos.csv"
_NIFTY = _REPO_ROOT / "data" / "backfill" / "nifty.csv"
_CAL = _REPO_ROOT / "models" / "calibrator.json"

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


def test_engine_regime_is_not_a_backdoor_into_the_score() -> None:
    config = load_config(env="dev", environ={})
    records = load_records_from_csv(_CSV)
    scorer = WeightedScorer(config.feature_weights, config.features)
    regime = NiftyRegime(_NIFTY)
    calibrator = load_calibrator(_CAL)
    assert calibrator.passes_reliability_gate  # so a real probability is actually emitted

    engine = VerdictEngine(
        repository=_ListRepo(records),
        calibrator=calibrator,
        scorer=scorer,
        config=config,
        regime=regime,
    )

    shown = 0
    cold_flagged = 0
    for rec in records:
        when = engine.decision_asof(rec)
        v_engine = engine.verdict_for(rec)
        # Official-only path: identical as-of clock, regime ABSENT.
        feats_off = build_features(rec, when, config=config.features)
        v_off = evaluate(rec, feats_off, scorer=scorer, calibrator=calibrator, config=config)

        # Exact equality: both None, or the same float — regime never moved the number.
        assert v_engine.probability == v_off.probability
        if v_engine.probability is not None:
            shown += 1
        if any("cold market" in w for w in v_engine.watch):
            cold_flagged += 1

    assert shown > 0  # the comparison actually exercised real (gated) probabilities
    assert cold_flagged > 0  # ...and the cold flag fired end-to-end (regime is live)


def test_engine_gates_probability_on_reliability() -> None:
    config = load_config(env="dev", environ={})
    records = load_records_from_csv(_CSV)
    scorer = WeightedScorer(config.feature_weights, config.features)
    regime = NiftyRegime(_NIFTY)
    rec = next(r for r in records if r.qib_sub is not None and r.listing_open is not None)

    ungated = VerdictEngine(
        repository=_ListRepo(records),
        calibrator=PlaceholderCalibrator(),
        scorer=scorer,
        config=config,
        regime=regime,
    )
    gated = VerdictEngine(
        repository=_ListRepo(records),
        calibrator=load_calibrator(_CAL),
        scorer=scorer,
        config=config,
        regime=regime,
    )

    v_ungated = ungated.verdict_for(rec)
    assert v_ungated.probability is None  # withheld until the gate passes (Inviolable Rule 1)
    assert "UNCALIBRATED" in v_ungated.reason  # banner present

    v_gated = gated.verdict_for(rec)
    assert v_gated.probability is not None  # gate passed -> a probability is shown
