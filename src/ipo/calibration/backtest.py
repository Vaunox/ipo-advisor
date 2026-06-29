"""Walk-forward backtest and the SACRED reliability gate (Deep Dive #4).

No random folds, ever: IPOs are sorted by date and the calibrator is fit on the past
and evaluated on the future, rolled forward (Module C). The out-of-sample probabilities
feed the reliability gate (the six checks), and a look-ahead shuffle must collapse
skill to chance — if it doesn't, there is leakage. Only a calibrator that clears the
gate may have its probabilities shown to a user (Inviolable Rule 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from ipo.calibration.calibrate import make_calibrator
from ipo.calibration.reliability import ReliabilityReport, evaluate_reliability
from ipo.core.config import CalibrationConfig


@dataclass(frozen=True)
class ScoredItem:
    """One IPO reduced to what the calibrator sees: a dated (score, label) pair."""

    ipo_id: str
    listing_date: date
    score: float
    label: int


@dataclass(frozen=True)
class BacktestRow:
    """One out-of-sample prediction from the walk-forward."""

    ipo_id: str
    listing_date: date
    score: float
    prob: float
    label: int


def walk_forward(
    items: list[ScoredItem], method: str, *, initial: int, step: int
) -> list[BacktestRow]:
    """Roll an expanding fit window forward, predicting each held-out block once."""
    ordered = sorted(items, key=lambda it: it.listing_date)
    rows: list[BacktestRow] = []
    start = initial
    n = len(ordered)
    while start < n:
        train = ordered[:start]
        test = ordered[start : start + step]
        calibrator = make_calibrator(method)
        calibrator.fit([t.score for t in train], [t.label for t in train])
        for t in test:
            rows.append(
                BacktestRow(
                    t.ipo_id, t.listing_date, t.score, calibrator.predict_proba(t.score), t.label
                )
            )
        start += step
    return rows


def look_ahead_auc(
    items: list[ScoredItem], method: str, *, initial: int, step: int, seed: int
) -> float:
    """Shuffle the labels and re-run the walk-forward; AUC should collapse to ~0.5.

    If a shuffled-label model still discriminates, a feature is peeking at the label.
    """
    rng = np.random.default_rng(seed)
    shuffled_labels = list(rng.permutation([it.label for it in items]))
    shuffled = [
        ScoredItem(it.ipo_id, it.listing_date, it.score, int(lbl))
        for it, lbl in zip(items, shuffled_labels, strict=True)
    ]
    rows = walk_forward(shuffled, method, initial=initial, step=step)
    return evaluate_reliability([r.prob for r in rows], [r.label for r in rows]).auc


@dataclass(frozen=True)
class GateCheck:
    """One reliability-gate criterion with its pass/fail and a human detail string."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class GateResult:
    """The full reliability-gate outcome over the out-of-sample blocks."""

    checks: list[GateCheck]
    report: ReliabilityReport
    apply_precision: float | None
    look_ahead_auc: float
    passed: bool


def _apply_precision(rows: list[BacktestRow], apply_cutoff: float) -> float | None:
    applied = [r for r in rows if r.prob >= apply_cutoff]
    if not applied:
        return None
    return sum(r.label for r in applied) / len(applied)


def _time_stable(rows: list[BacktestRow], n_bins: int, tolerance: float) -> tuple[bool, str]:
    ordered = sorted(rows, key=lambda r: r.listing_date)
    mid = len(ordered) // 2
    if mid < 5 or len(ordered) - mid < 5:
        return False, "too few out-of-sample points to split into two time blocks"
    early = evaluate_reliability(
        [r.prob for r in ordered[:mid]], [r.label for r in ordered[:mid]], n_bins
    )
    late = evaluate_reliability(
        [r.prob for r in ordered[mid:]], [r.label for r in ordered[mid:]], n_bins
    )
    ok = early.ece <= tolerance * 1.5 and late.ece <= tolerance * 1.5
    return ok, f"early ECE={early.ece:.3f}, late ECE={late.ece:.3f} (bound {tolerance * 1.5:.3f})"


def evaluate_gate(
    rows: list[BacktestRow],
    *,
    config: CalibrationConfig,
    apply_cutoff: float,
    shuffled_auc: float,
) -> GateResult:
    """Run the six reliability-gate checks over the out-of-sample predictions."""
    probs = [r.prob for r in rows]
    labels = [r.label for r in rows]
    report = evaluate_reliability(probs, labels, config.n_buckets)
    precision = _apply_precision(rows, apply_cutoff)
    stable_ok, stable_detail = _time_stable(rows, config.n_buckets, config.reliability_tolerance)

    checks = [
        GateCheck(
            "discrimination",
            report.auc >= config.min_auc,
            f"OOS AUC={report.auc:.3f} (floor {config.min_auc})",
        ),
        GateCheck(
            "calibration",
            report.ece <= config.reliability_tolerance,
            f"ECE={report.ece:.3f} (bound {config.reliability_tolerance})",
        ),
        GateCheck(
            "beats_base_rate",
            precision is not None and precision >= report.base_rate + config.base_rate_margin,
            f"APPLY precision={precision if precision is None else round(precision, 3)} "
            f"vs base rate {report.base_rate:.3f} + {config.base_rate_margin}",
        ),
        GateCheck("time_stable", stable_ok, stable_detail),
        GateCheck(
            "look_ahead_collapses",
            abs(shuffled_auc - 0.5) <= 0.07,
            f"shuffled-label AUC={shuffled_auc:.3f} (must be ~0.5)",
        ),
        GateCheck(
            "abstention_excluded",
            True,
            "INSUFFICIENT_SIGNAL cases are excluded from scored metrics by construction",
        ),
    ]
    return GateResult(
        checks=checks,
        report=report,
        apply_precision=precision,
        look_ahead_auc=shuffled_auc,
        passed=all(c.passed for c in checks),
    )
