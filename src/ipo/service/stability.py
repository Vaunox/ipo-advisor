"""Cross-break calibration stability across the T+3 settlement cutover (A4 part 2).

SEBI shortened the IPO listing timeline from T+6 to T+3 working days (mandatory 1 Dec
2023 — ``core.constants.T3_MANDATORY_CUTOVER``). The 2021+ backfill straddles this break,
which shortens the ASBA blocked-capital window and could shift listing-day behaviour. This
module encodes the break as a dummy and reports, honestly, whether the *already-calibrated*
model behaves differently on either side.

It is a read-only reported check: the ``t3_regime`` dummy is never added to the score and
the calibrator is never refit. If a real difference showed up, the action would be an
operator decision (recalibrate on post-cutover data) — this module only surfaces it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ipo.calibration.benchmark import BenchRow
from ipo.core.constants import T3_MANDATORY_CUTOVER
from ipo.service.monitoring import AccuracySnapshot, snapshot_from_rows


def t3_regime(listing_date: date) -> int:
    """The T+3 structural dummy: 1 if the IPO listed on/after the mandatory cutover.

    Operationalized on the listing date (the outcome date carried by every OOS row);
    issues opening on/after the cutover list a few days later, so this cleanly separates
    the pre- and post-T+3 regimes.
    """
    return int(listing_date >= T3_MANDATORY_CUTOVER)


@dataclass(frozen=True)
class CrossBreakStability:
    """Pre- vs post-cutover accuracy snapshots and an honest read on whether it shifted."""

    cutover: date
    pre: AccuracySnapshot
    post: AccuracySnapshot
    ece_tolerance: float
    min_slice: int

    @property
    def ece_shift(self) -> float:
        """Post-cutover ECE minus pre-cutover ECE (positive = worse calibration after)."""
        return self.post.ece - self.pre.ece

    def _precision_cis_overlap(self) -> bool:
        """True if the pre/post APPLY-precision 95% intervals overlap (or one is empty)."""
        if self.pre.apply_precision is None or self.post.apply_precision is None:
            return True  # a side with no APPLYs can't contradict the other
        return (
            self.pre.precision_ci_low <= self.post.precision_ci_high
            and self.post.precision_ci_low <= self.pre.precision_ci_high
        )

    @property
    def verdict(self) -> str:
        """A plain-language, honest read on cross-break calibration stability."""
        if self.pre.n < self.min_slice or self.post.n < self.min_slice:
            return f"INCONCLUSIVE - thin slice (pre n={self.pre.n}, post n={self.post.n})"
        ece_ok = abs(self.ece_shift) <= self.ece_tolerance
        prec_ok = self._precision_cis_overlap()
        if ece_ok and prec_ok:
            return (
                "STABLE - ECE shift within tolerance and APPLY-precision CIs overlap; "
                "the calibrator holds across the break"
            )
        reasons: list[str] = []
        if not ece_ok:
            reasons.append(f"ECE shifted {self.ece_shift:+.3f} (> {self.ece_tolerance:.3f} tol)")
        if not prec_ok:
            reasons.append("APPLY-precision CIs do not overlap")
        return "DIFFERENCE across the break: " + "; ".join(reasons)


def cross_break_stability(
    rows: list[BenchRow],
    *,
    apply_cutoff: float,
    n_bins: int = 10,
    ece_tolerance: float = 0.03,
    min_slice: int = 20,
) -> CrossBreakStability:
    """Split the OOS rows by the T+3 dummy and snapshot calibration on each side.

    Args:
        rows: Walk-forward out-of-sample rows (calibrated ``model_prob`` + realized label).
        apply_cutoff: The APPLY probability cutoff.
        n_bins: Reliability-diagram bin count for the ECE.
        ece_tolerance: ECE shift beyond which the break is flagged as a difference.
        min_slice: Minimum rows on a side before the verdict is anything but inconclusive.

    Returns:
        The pre/post snapshots plus an honest stability verdict — a reported check only.
    """
    pre = [r for r in rows if t3_regime(r.listing_date) == 0]
    post = [r for r in rows if t3_regime(r.listing_date) == 1]
    return CrossBreakStability(
        cutover=T3_MANDATORY_CUTOVER,
        pre=snapshot_from_rows(pre, apply_cutoff=apply_cutoff, n_bins=n_bins),
        post=snapshot_from_rows(post, apply_cutoff=apply_cutoff, n_bins=n_bins),
        ece_tolerance=ece_tolerance,
        min_slice=min_slice,
    )
