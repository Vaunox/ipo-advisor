"""Live verdict-accuracy monitoring (A4 — operate-phase hardening).

The backtest earns the right to ship a probability; monitoring keeps that right honest
*after* launch. As live IPOs list, their realized outcomes accumulate — this module
compares a recent window of realized APPLY precision and ECE against the walk-forward
out-of-sample baseline the calibrator was gated on, and raises an alert only on a
*real* departure (not small-sample noise).

Two guardrails keep the alert trustworthy:

* **Precision** uses the same Wilson interval as the benchmark (``calibration.benchmark``):
  a drift alert fires only when the recent window's precision is below the baseline
  *even at the optimistic end of its 95% interval* — so a thin unlucky window does not
  cry wolf.
* **ECE** fires when recent calibration error exceeds the baseline by more than a
  tolerance.

This is a read-only operator ritual (run periodically, e.g. after a batch of listings),
not a standing daemon and not a change to the score — it never touches the calibrator.
"""

from __future__ import annotations

from dataclasses import dataclass

from ipo.calibration.benchmark import BenchRow, wilson_ci
from ipo.calibration.reliability import evaluate_reliability


@dataclass(frozen=True)
class AccuracySnapshot:
    """APPLY precision (with a Wilson 95% interval) and ECE over a set of outcomes."""

    n: int
    n_apply: int
    apply_precision: float | None
    precision_ci_low: float
    precision_ci_high: float
    ece: float
    base_rate: float


@dataclass(frozen=True)
class DriftAlert:
    """One breached guardrail: the metric, its baseline, the observed value, and why."""

    metric: str
    baseline: float
    observed: float
    detail: str

    def __str__(self) -> str:
        """Render the alert as a single human-readable line."""
        return f"[{self.metric}] {self.detail}"


@dataclass(frozen=True)
class MonitorResult:
    """Baseline vs recent-window snapshots plus any drift alerts that fired."""

    baseline: AccuracySnapshot
    window: AccuracySnapshot
    alerts: tuple[DriftAlert, ...]
    insufficient_sample: bool

    @property
    def ok(self) -> bool:
        """True when no drift alert fired.

        A thin window (``insufficient_sample``) also reads as ``ok`` because no departure
        was *detected* — inspect ``insufficient_sample`` separately to know the check was
        inconclusive rather than affirmatively healthy.
        """
        return not self.alerts


def snapshot(
    probs: list[float], labels: list[int], *, apply_cutoff: float, n_bins: int = 10
) -> AccuracySnapshot:
    """Compute the APPLY precision (+ Wilson CI) and ECE for one set of realized outcomes.

    Args:
        probs: Calibrated probabilities for each realized IPO.
        labels: 1 if the IPO listed positive net-of-cost, else 0.
        apply_cutoff: The probability at or above which the verdict is APPLY.
        n_bins: Reliability-diagram bin count for the ECE.

    Returns:
        The snapshot; ``apply_precision`` is ``None`` when nothing cleared the cutoff.
    """
    rel = evaluate_reliability(probs, labels, n_bins)
    applied = [(p, y) for p, y in zip(probs, labels, strict=True) if p >= apply_cutoff]
    n_apply = len(applied)
    if n_apply == 0:
        return AccuracySnapshot(len(labels), 0, None, 0.0, 0.0, rel.ece, rel.base_rate)
    positives = sum(y for _, y in applied)
    lo, hi = wilson_ci(positives, n_apply)
    return AccuracySnapshot(
        n=len(labels),
        n_apply=n_apply,
        apply_precision=positives / n_apply,
        precision_ci_low=lo,
        precision_ci_high=hi,
        ece=rel.ece,
        base_rate=rel.base_rate,
    )


def snapshot_from_rows(
    rows: list[BenchRow], *, apply_cutoff: float, n_bins: int = 10
) -> AccuracySnapshot:
    """Convenience wrapper: build a snapshot from walk-forward ``BenchRow`` outcomes."""
    return snapshot(
        [r.model_prob for r in rows],
        [r.label for r in rows],
        apply_cutoff=apply_cutoff,
        n_bins=n_bins,
    )


def evaluate_drift(
    baseline: AccuracySnapshot,
    window: AccuracySnapshot,
    *,
    ece_tolerance: float = 0.03,
    min_window: int = 20,
) -> MonitorResult:
    """Compare a recent window against the baseline and return any drift alerts.

    A precision alert fires only when the window's precision is below the baseline even
    at the top of its 95% Wilson interval (a real departure, not noise). An ECE alert
    fires when the window's calibration error exceeds the baseline by more than
    ``ece_tolerance``. Windows smaller than ``min_window`` are reported as insufficient
    rather than judged.

    Args:
        baseline: The walk-forward out-of-sample snapshot the calibrator was gated on.
        window: The recent realized-outcome snapshot to test for drift.
        ece_tolerance: Absolute ECE increase over baseline that trips the alert.
        min_window: Minimum realized outcomes before drift is judged at all.

    Returns:
        A ``MonitorResult`` whose ``ok`` is True when nothing tripped.
    """
    if window.n < min_window:
        return MonitorResult(baseline, window, (), insufficient_sample=True)

    alerts: list[DriftAlert] = []
    if (
        baseline.apply_precision is not None
        and window.apply_precision is not None
        and window.n_apply > 0
        and window.precision_ci_high < baseline.apply_precision
    ):
        alerts.append(
            DriftAlert(
                metric="apply_precision",
                baseline=baseline.apply_precision,
                observed=window.apply_precision,
                detail=(
                    f"recent APPLY precision {window.apply_precision:.0%} "
                    f"(95% CI up to {window.precision_ci_high:.0%}, n={window.n_apply}) "
                    f"is below the backtest baseline {baseline.apply_precision:.0%}"
                ),
            )
        )
    if window.ece > baseline.ece + ece_tolerance:
        alerts.append(
            DriftAlert(
                metric="ece",
                baseline=baseline.ece,
                observed=window.ece,
                detail=(
                    f"recent ECE {window.ece:.3f} exceeds the baseline {baseline.ece:.3f} "
                    f"by more than the {ece_tolerance:.3f} tolerance"
                ),
            )
        )
    return MonitorResult(baseline, window, tuple(alerts), insufficient_sample=False)
