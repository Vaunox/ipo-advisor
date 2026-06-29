"""GATE 4 (integration): the official model passes the reliability gate on real data.

Reproduces the Phase-4 result on the committed backfill CSV, so the gate is a
CI-enforced invariant: discrimination, calibration, beats-base-rate, time-stability,
and — critically — the look-ahead shuffle collapsing skill to chance (no leakage).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ipo.calibration.backtest import evaluate_gate, look_ahead_auc, walk_forward
from ipo.calibration.dataset import load_records_from_csv, scored_items_from_records
from ipo.core.config import load_config
from ipo.model.scorer import WeightedScorer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CSV = _REPO_ROOT / "data" / "backfill" / "mainboard_ipos.csv"

pytestmark = pytest.mark.skipif(not _CSV.is_file(), reason="backfill CSV not present")


def test_official_model_passes_the_reliability_gate() -> None:
    config = load_config(env="dev", environ={})
    cal = config.calibration
    records = load_records_from_csv(_CSV)
    items = scored_items_from_records(
        records,
        WeightedScorer(config.feature_weights, config.features),
        features_config=config.features,
        sell_costs=config.sell_costs,
        nominal_application_value=cal.nominal_application_value,
    )
    assert len(items) >= 100  # the >=100 mainboard sample the gate requires

    rows = walk_forward(
        items, cal.method, initial=cal.walk_forward_initial, step=cal.walk_forward_step
    )
    shuffled = look_ahead_auc(
        items,
        cal.method,
        initial=cal.walk_forward_initial,
        step=cal.walk_forward_step,
        seed=cal.random_seed,
    )
    gate = evaluate_gate(
        rows, config=cal, apply_cutoff=config.verdict_thresholds.apply, shuffled_auc=shuffled
    )

    assert gate.passed, [(c.name, c.detail) for c in gate.checks if not c.passed]
    assert gate.report.auc > 0.70  # genuine discrimination
    assert gate.report.ece <= cal.reliability_tolerance  # calibrated
    assert abs(gate.look_ahead_auc - 0.5) <= 0.10  # leakage firewall holds
