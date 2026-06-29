"""GATE 4 (integration): Layer 3 loads the persisted calibrator and shows a probability.

Once the gate passes, the persisted calibrator replaces the placeholder: ``evaluate``
now surfaces a calibrated probability (no "uncalibrated" banner). This is the line
between asserting confidence and earning it (Inviolable Rule 1).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from ipo.calibration.calibrate import load_calibrator
from ipo.core.config import load_config
from ipo.core.constants import IST
from ipo.core.types import IPORecord, Segment
from ipo.features.build import build_features
from ipo.model.reason import UNCALIBRATED_BANNER
from ipo.model.scorer import WeightedScorer
from ipo.model.verdict import evaluate

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CALIBRATOR = _REPO_ROOT / "models" / "calibrator.json"

pytestmark = pytest.mark.skipif(not _CALIBRATOR.is_file(), reason="calibrator not present")


def _strong_record() -> IPORecord:
    return IPORecord(
        ipo_id="strongco",
        name="StrongCo Ltd",
        segment=Segment.MAINBOARD,
        price_band_low=475.0,
        price_band_high=500.0,
        open_date=date(2024, 1, 1),
        close_date=date(2024, 1, 3),
        listing_date=date(2024, 1, 8),
        qib_sub=180.0,
        nii_sub=70.0,
        retail_sub=14.0,
        captured_at=datetime(2024, 1, 3, 18, tzinfo=IST),
    )


def test_persisted_calibrator_passed_the_gate() -> None:
    calibrator = load_calibrator(_CALIBRATOR)
    assert calibrator.passes_reliability_gate is True


def test_layer3_shows_calibrated_probability() -> None:
    config = load_config(env="dev", environ={})
    calibrator = load_calibrator(_CALIBRATOR)
    scorer = WeightedScorer(config.feature_weights, config.features)
    rec = _strong_record()
    asof = datetime(2024, 1, 3, 18, tzinfo=IST)
    feats = build_features(rec, asof, config=config.features)  # GMP absent (Phase 5), QIB present

    verdict = evaluate(rec, feats, scorer=scorer, calibrator=calibrator, config=config)

    # Gate passed -> a real probability is shown, with no uncalibrated banner.
    assert verdict.probability is not None
    assert 0.0 <= verdict.probability <= 1.0
    assert UNCALIBRATED_BANNER not in verdict.reason
    # A heavily-subscribed issue should land APPLY/MARGINAL, not SKIP.
    assert verdict.verdict.value in {"APPLY", "MARGINAL"}
