"""Layer 4 — backtest & calibration (the load-bearing, SACRED gate).

Turns a raw score into a trustworthy probability and an earned verdict. Nothing
user-facing ships until ``evaluate_gate`` passes on the out-of-sample blocks and the
look-ahead shuffle collapses skill to chance (Inviolable Rule 1).
"""

from ipo.calibration.backtest import (
    BacktestRow,
    GateResult,
    ScoredItem,
    evaluate_gate,
    look_ahead_auc,
    walk_forward,
)
from ipo.calibration.calibrate import (
    CalibratorMeta,
    IsotonicCalibrator,
    PlattCalibrator,
    feature_code_hash,
    load_calibrator,
    make_calibrator,
    save_calibrator,
)
from ipo.calibration.label import is_positive, net_listing_return
from ipo.calibration.reliability import ReliabilityReport, evaluate_reliability

__all__ = [
    "BacktestRow",
    "GateResult",
    "ScoredItem",
    "evaluate_gate",
    "look_ahead_auc",
    "walk_forward",
    "CalibratorMeta",
    "IsotonicCalibrator",
    "PlattCalibrator",
    "feature_code_hash",
    "load_calibrator",
    "make_calibrator",
    "save_calibrator",
    "is_positive",
    "net_listing_return",
    "ReliabilityReport",
    "evaluate_reliability",
]
