"""T+3 cross-break stability: the regime dummy, the split, and the honest verdict."""

from __future__ import annotations

from datetime import date

from ipo.calibration.benchmark import BenchRow
from ipo.service.monitoring import AccuracySnapshot
from ipo.service.stability import CrossBreakStability, cross_break_stability, t3_regime

_CUTOFF = 0.65


def _row(listing: date, *, label: int, prob: float) -> BenchRow:
    return BenchRow("ipo", listing, label, 0.1, 5.0, 5.0, prob)


def _snap(
    *, precision: float | None, ci: tuple[float, float], ece: float, n: int
) -> AccuracySnapshot:
    return AccuracySnapshot(
        n=n,
        n_apply=max(1, n // 2),
        apply_precision=precision,
        precision_ci_low=ci[0],
        precision_ci_high=ci[1],
        ece=ece,
        base_rate=0.7,
    )


def _stability(pre: AccuracySnapshot, post: AccuracySnapshot) -> CrossBreakStability:
    return CrossBreakStability(
        cutover=date(2023, 12, 1), pre=pre, post=post, ece_tolerance=0.03, min_slice=20
    )


def test_t3_regime_boundary() -> None:
    assert t3_regime(date(2023, 11, 30)) == 0
    assert t3_regime(date(2023, 12, 1)) == 1  # mandatory cutover day is post-regime
    assert t3_regime(date(2024, 6, 1)) == 1
    assert t3_regime(date(2021, 1, 1)) == 0


def test_cross_break_splits_by_listing_date() -> None:
    rows = [
        _row(date(2023, 6, 1), label=1, prob=0.8),
        _row(date(2023, 9, 1), label=0, prob=0.7),
        _row(date(2024, 2, 1), label=1, prob=0.9),
    ]
    result = cross_break_stability(rows, apply_cutoff=_CUTOFF, min_slice=1)
    assert result.pre.n == 2
    assert result.post.n == 1
    assert result.cutover == date(2023, 12, 1)


def test_verdict_stable_when_ece_close_and_cis_overlap() -> None:
    pre = _snap(precision=0.85, ci=(0.75, 0.92), ece=0.06, n=120)
    post = _snap(precision=0.82, ci=(0.70, 0.90), ece=0.08, n=80)
    assert _stability(pre, post).verdict.startswith("STABLE")


def test_verdict_inconclusive_when_slice_thin() -> None:
    pre = _snap(precision=0.85, ci=(0.75, 0.92), ece=0.06, n=120)
    post = _snap(precision=0.5, ci=(0.2, 0.8), ece=0.20, n=8)
    assert _stability(pre, post).verdict.startswith("INCONCLUSIVE")


def test_verdict_difference_on_ece_blowout() -> None:
    pre = _snap(precision=0.85, ci=(0.75, 0.92), ece=0.06, n=120)
    post = _snap(precision=0.84, ci=(0.72, 0.91), ece=0.18, n=80)
    verdict = _stability(pre, post).verdict
    assert verdict.startswith("DIFFERENCE")
    assert "ECE shifted" in verdict


def test_verdict_difference_on_disjoint_precision() -> None:
    pre = _snap(precision=0.90, ci=(0.82, 0.96), ece=0.06, n=120)
    post = _snap(precision=0.55, ci=(0.40, 0.70), ece=0.07, n=80)
    verdict = _stability(pre, post).verdict
    assert verdict.startswith("DIFFERENCE")
    assert "CIs do not overlap" in verdict
