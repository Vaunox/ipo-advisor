"""Step 1 (Phase 6): market_regime is wired in FLAG-ONLY — weight 0, calibrator untouched.

The load-bearing guarantee: populating ``market_regime`` live (as the cold flag needs) must
leave the calibrated out-of-sample probabilities **byte-for-byte identical** to the
regime-free official model. If any OOS probability differs, regime is leaking into the
score — a calibration-rule violation — and this test fails. Equality is asserted exactly,
not within a tolerance.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ipo.calibration.backtest import walk_forward
from ipo.calibration.dataset import load_records_from_csv, scored_items_from_records
from ipo.calibration.regime import NiftyRegime
from ipo.core.config import load_config
from ipo.model.scorer import WeightedScorer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CSV = _REPO_ROOT / "data" / "backfill" / "mainboard_ipos.csv"
_NIFTY = _REPO_ROOT / "data" / "backfill" / "nifty.csv"

pytestmark = pytest.mark.skipif(
    not (_CSV.is_file() and _NIFTY.is_file()), reason="backfill data not present"
)


def test_market_regime_weight_is_zero() -> None:
    # The flag-only invariant lives in config: regime must contribute 0 to the score.
    config = load_config(env="dev", environ={})
    assert config.feature_weights.get("market_regime", 0.0) == 0.0


def test_regime_populated_leaves_oos_probabilities_byte_identical() -> None:
    config = load_config(env="dev", environ={})
    cal = config.calibration
    records = load_records_from_csv(_CSV)
    scorer = WeightedScorer(config.feature_weights, config.features)
    regime = NiftyRegime(_NIFTY)

    common = {
        "features_config": config.features,
        "sell_costs": config.sell_costs,
        "nominal_application_value": cal.nominal_application_value,
    }
    items_baseline = scored_items_from_records(records, scorer, **common)  # regime absent
    items_regime = scored_items_from_records(
        records, scorer, market_regime_of=regime.market_regime_feature, **common
    )

    # Guard against a vacuous pass: regime must actually be exercised — some IPOs non-None,
    # and at least one in the cold (<= -0.3) flag zone — else equality proves nothing.
    populated = [regime.market_regime_feature(r.close_date) for r in records]
    assert any(v is not None for v in populated)
    assert any(v is not None and v <= config.verdict_thresholds.cold_regime_flag for v in populated)

    # Raw scores identical (weight 0 -> exactly-zero contribution from the populated feature).
    assert [it.score for it in items_baseline] == [it.score for it in items_regime]

    # ...therefore the calibrated OOS probabilities are byte-for-byte identical (exact ==).
    rows_b = walk_forward(
        items_baseline, cal.method, initial=cal.walk_forward_initial, step=cal.walk_forward_step
    )
    rows_r = walk_forward(
        items_regime, cal.method, initial=cal.walk_forward_initial, step=cal.walk_forward_step
    )
    assert [r.ipo_id for r in rows_b] == [r.ipo_id for r in rows_r]
    assert [r.prob for r in rows_b] == [r.prob for r in rows_r]
