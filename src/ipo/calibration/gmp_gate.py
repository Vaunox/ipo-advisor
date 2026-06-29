"""The GMP re-calibration gate (Deep Dive #5, Module D) — GMP must earn its place.

Adding GMP is not assumed to help; it must be *shown* to help. This runs the same
walk-forward calibration **with** and **without** GMP on the same sample and compares
reliability: GMP stays only if the recalibrated model is **at least as well-calibrated**
as the official-only model. If the noisy series degrades calibration, GMP comes out —
a striking but legitimate outcome given GMP's noise.

The comparison is at the (score, label) level: callers build the two item sets — one
scored without GMP, one with — sharing labels and dates, so only the feature changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from ipo.calibration.backtest import ScoredItem, walk_forward
from ipo.calibration.reliability import ReliabilityReport, evaluate_reliability


@dataclass(frozen=True)
class GmpGateResult:
    """Outcome of the with-vs-without-GMP re-calibration comparison."""

    without_gmp: ReliabilityReport
    with_gmp: ReliabilityReport
    keep_gmp: bool
    reason: str


def gmp_recalibration_gate(
    items_without_gmp: list[ScoredItem],
    items_with_gmp: list[ScoredItem],
    *,
    method: str,
    initial: int,
    step: int,
    n_buckets: int = 10,
    ece_tolerance: float = 0.0,
    auc_tolerance: float = 0.02,
) -> GmpGateResult:
    """Compare with vs without GMP; keep GMP only if it worsens neither metric.

    GMP stays only if it is **at least as well-calibrated** (ECE no worse) *and* does
    not degrade **discrimination** (AUC no worse). The AUC guard matters because a
    pure-noise feature can collapse discrimination yet stay "calibrated" by predicting
    the base rate everywhere — that must not pass.

    Args:
        items_without_gmp: dated (score, label) pairs scored on official features only.
        items_with_gmp: the same IPOs scored with GMP added (same labels/dates).
        method: calibrator family (``platt``/``isotonic``).
        initial: walk-forward initial training window (identical to the Phase-4 run).
        step: walk-forward roll size.
        n_buckets: reliability bins.
        ece_tolerance: slack on ECE before GMP is rejected.
        auc_tolerance: slack on AUC before GMP is rejected.
    """
    rows_wo = walk_forward(items_without_gmp, method, initial=initial, step=step)
    rows_w = walk_forward(items_with_gmp, method, initial=initial, step=step)
    rep_wo = evaluate_reliability([r.prob for r in rows_wo], [r.label for r in rows_wo], n_buckets)
    rep_w = evaluate_reliability([r.prob for r in rows_w], [r.label for r in rows_w], n_buckets)

    ece_ok = rep_w.ece <= rep_wo.ece + ece_tolerance
    auc_ok = rep_w.auc >= rep_wo.auc - auc_tolerance
    keep = ece_ok and auc_ok
    if keep:
        reason = (
            f"GMP kept: ECE {rep_w.ece:.3f} vs {rep_wo.ece:.3f} and "
            f"AUC {rep_w.auc:.3f} vs {rep_wo.auc:.3f} — earned its weight"
        )
    elif not auc_ok:
        reason = (
            f"GMP removed: it degraded discrimination (AUC {rep_w.auc:.3f} < "
            f"official-only {rep_wo.auc:.3f}) — noise, not signal"
        )
    else:
        reason = (
            f"GMP removed: it worsened calibration (ECE {rep_w.ece:.3f} > "
            f"official-only {rep_wo.ece:.3f}) — did not earn its weight"
        )
    return GmpGateResult(without_gmp=rep_wo, with_gmp=rep_w, keep_gmp=keep, reason=reason)
