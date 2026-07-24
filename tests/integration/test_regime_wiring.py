"""Step 1 (Phase 6): market_regime is wired in FLAG-ONLY — weight 0, calibrator untouched.

The load-bearing guarantee: populating ``market_regime`` live (as the cold flag needs) must
leave the calibrated out-of-sample probabilities **byte-for-byte identical** to the
regime-free official model. If any OOS probability differs, regime is leaking into the
score — a calibration-rule violation — and this test fails. Equality is asserted exactly,
not within a tolerance.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ipo.calibration.backtest import walk_forward
from ipo.calibration.calibrate import load_calibrator
from ipo.calibration.dataset import load_records_from_csv, scored_items_from_records
from ipo.calibration.regime import NiftyRegime
from ipo.core.config import load_config
from ipo.core.types import IPORecord, ListingLabel
from ipo.model.scorer import WeightedScorer
from ipo.service.runner import build_service
from ipo.service.transitions import TransitionStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CSV = _REPO_ROOT / "data" / "backfill" / "mainboard_ipos.csv"
_NIFTY = _REPO_ROOT / "data" / "backfill" / "nifty.csv"
_CAL = _REPO_ROOT / "models" / "calibrator.json"

pytestmark = pytest.mark.skipif(
    not (_CSV.is_file() and _NIFTY.is_file()), reason="backfill data not present"
)


class _EmptyRepo:
    """A repository with no records — enough to compose the service and read its wired regime."""

    def upsert(self, record: IPORecord) -> None: ...
    def upsert_many(self, records: list[IPORecord]) -> None: ...
    def get(self, ipo_id: str) -> IPORecord | None:
        return None

    def list_all(self) -> list[IPORecord]:
        return []

    def save_labels(self, labels: list[ListingLabel]) -> None: ...
    def load_labels(self) -> list[ListingLabel]:
        return []


def test_market_regime_weight_is_zero() -> None:
    # The flag-only invariant lives in config: regime must contribute 0 to the score.
    config = load_config(env="dev", environ={})
    assert config.feature_weights.get("market_regime", 0.0) == 0.0


@pytest.mark.skipif(not _CAL.is_file(), reason="calibrator artifact not present")
def test_runner_threads_regime_config_into_the_composed_engine() -> None:
    """F-1 anti-drift — the one the shipped-default byte-equality CANNOT provide: at the defaults a
    dropped runner wire is invisible (the fallback default equals the shipped config value).
    Only a NON-default config proves runner.py threads `features.regime.*` into NiftyRegime rather
    than silently falling back. If any wire is dropped, that field reads the __init__ default (63 /
    0.08 / -0.05) != the override and this fails."""
    cfg = load_config(
        env="dev",
        environ={},
        overrides={
            "features": {"regime": {"trend_days": 40, "trend_scale": 0.11, "drawdown_floor": -0.2}}
        },
    )
    store = TransitionStore(Path(tempfile.mkdtemp()) / "verdict_transitions.json")
    svc = build_service(
        cfg,
        repository=_EmptyRepo(),
        calibrator=load_calibrator(_CAL),
        nifty_path=_NIFTY,
        transition_store=store,
    )
    reg = svc.engine._regime
    assert reg is not None
    assert reg._trend_days == 40  # trend window threaded from config
    assert reg._trend_scale == 0.11  # trend scale threaded from config
    assert reg._floor == -0.2  # drawdown floor threaded from config


def test_regime_populated_leaves_oos_probabilities_byte_identical() -> None:
    config = load_config(env="dev", environ={})
    cal = config.calibration
    records = load_records_from_csv(_CSV)
    scorer = WeightedScorer(config.feature_weights, config.features)
    regime = NiftyRegime(_NIFTY)

    items_baseline = scored_items_from_records(  # regime absent
        records,
        scorer,
        features_config=config.features,
        sell_costs=config.sell_costs,
        nominal_application_value=cal.nominal_application_value,
    )
    items_regime = scored_items_from_records(
        records,
        scorer,
        features_config=config.features,
        sell_costs=config.sell_costs,
        nominal_application_value=cal.nominal_application_value,
        market_regime_of=regime.market_regime_feature,
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
