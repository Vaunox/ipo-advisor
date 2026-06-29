"""Calibration machinery on synthetic data with known ground truth.

These validate the SACRED layer's logic deterministically: a calibratable signal
passes the gate; shuffled labels collapse discrimination to chance (the look-ahead
firewall); the reliability metrics and Platt/isotonic fits behave.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from ipo.calibration.backtest import ScoredItem, evaluate_gate, look_ahead_auc, walk_forward
from ipo.calibration.calibrate import (
    CalibratorMeta,
    IsotonicCalibrator,
    PlattCalibrator,
    load_calibrator,
    save_calibrator,
)
from ipo.calibration.label import is_positive, net_listing_return
from ipo.calibration.reliability import (
    auc_score,
    brier_score,
    evaluate_reliability,
    reliability_bins,
)
from ipo.core.config import CalibrationConfig, SellCosts


def _synthetic_items(n: int, *, signal: float, seed: int) -> list[ScoredItem]:
    """Scores ~N(0,1); P(label=1)=sigmoid(signal*score) — a calibratable signal."""
    rng = np.random.default_rng(seed)
    scores = rng.normal(0, 1, n)
    probs = 1.0 / (1.0 + np.exp(-signal * scores))
    labels = (rng.random(n) < probs).astype(int)
    start = date(2021, 1, 1)
    return [
        ScoredItem(f"ipo{i}", start + timedelta(days=i * 3), float(scores[i]), int(labels[i]))
        for i in range(n)
    ]


# --- label -----------------------------------------------------------------


def test_net_return_positive_and_cost_drag() -> None:
    costs = SellCosts()
    gross_up = net_listing_return(100.0, 140.0, costs, nominal_application_value=15000)
    assert gross_up > 0.35  # ~+40% minus small costs
    # A tiny gross gain is eaten by costs -> net negative -> labelled 0.
    net_tiny = net_listing_return(100.0, 100.2, costs, nominal_application_value=15000)
    assert is_positive(net_tiny) == 0


# --- reliability metrics ----------------------------------------------------


def test_auc_perfect_and_chance() -> None:
    assert auc_score([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == 1.0
    assert auc_score([0.5, 0.5, 0.5, 0.5], [0, 1, 0, 1]) == 0.5


def test_brier_and_bins() -> None:
    assert brier_score([1.0, 0.0], [1, 0]) == 0.0
    bins, ece = reliability_bins([0.05, 0.95], [0, 1], n_bins=10)
    assert ece < 0.1
    assert len(bins) == 2


# --- calibrators ------------------------------------------------------------


def test_platt_recovers_calibration() -> None:
    items = _synthetic_items(400, signal=2.0, seed=1)
    cal = PlattCalibrator()
    cal.fit([it.score for it in items], [it.label for it in items])
    # Monotonic in score, bounded in (0,1).
    assert 0.0 < cal.predict_proba(-3.0) < cal.predict_proba(3.0) < 1.0


def test_platt_unfitted_raises() -> None:
    with pytest.raises(RuntimeError):
        PlattCalibrator().predict_proba(0.0)


def test_isotonic_is_monotone() -> None:
    items = _synthetic_items(300, signal=2.0, seed=2)
    cal = IsotonicCalibrator()
    cal.fit([it.score for it in items], [it.label for it in items])
    lo, hi = cal.predict_proba(-2.0), cal.predict_proba(2.0)
    assert 0.0 <= lo <= hi <= 1.0


def test_save_load_roundtrip(tmp_path: Path) -> None:
    items = _synthetic_items(200, signal=2.0, seed=3)
    cal = PlattCalibrator()
    cal.fit([it.score for it in items], [it.label for it in items])
    cal.set_gate(True)
    meta = CalibratorMeta("hash", "net>0", len(items), 0.5)
    path = tmp_path / "cal.json"
    save_calibrator(cal, path, meta=meta)
    loaded = load_calibrator(path)
    assert loaded.passes_reliability_gate is True
    assert loaded.predict_proba(1.0) == pytest.approx(cal.predict_proba(1.0))


# --- walk-forward + gate ----------------------------------------------------


def test_walk_forward_produces_oos_rows() -> None:
    items = _synthetic_items(200, signal=2.0, seed=4)
    rows = walk_forward(items, "platt", initial=60, step=20)
    assert len(rows) == 140  # 200 - 60 initial
    assert all(0.0 <= r.prob <= 1.0 for r in rows)


def test_look_ahead_shuffle_collapses_discrimination() -> None:
    items = _synthetic_items(300, signal=2.0, seed=5)
    real = walk_forward(items, "platt", initial=60, step=20)
    real_auc = evaluate_reliability([r.prob for r in real], [r.label for r in real]).auc
    shuffled_auc = look_ahead_auc(items, "platt", initial=60, step=20, seed=5)
    assert real_auc > 0.6  # genuine signal discriminates
    assert abs(shuffled_auc - 0.5) <= 0.1  # shuffled collapses to chance


def test_gate_passes_on_calibratable_signal() -> None:
    items = _synthetic_items(400, signal=2.5, seed=6)
    rows = walk_forward(items, "platt", initial=80, step=20)
    shuffled = look_ahead_auc(items, "platt", initial=80, step=20, seed=6)
    cfg = CalibrationConfig(min_auc=0.6, reliability_tolerance=0.15)
    gate = evaluate_gate(rows, config=cfg, apply_cutoff=0.65, shuffled_auc=shuffled)
    assert {c.name for c in gate.checks} == {
        "discrimination",
        "calibration",
        "beats_base_rate",
        "time_stable",
        "look_ahead_collapses",
        "abstention_excluded",
    }
    assert next(c for c in gate.checks if c.name == "discrimination").passed
    assert next(c for c in gate.checks if c.name == "look_ahead_collapses").passed
