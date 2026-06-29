"""Benchmark helpers: Wilson intervals, selectors, precision/loss accounting."""

from __future__ import annotations

from datetime import date

import pytest

from ipo.calibration.benchmark import (
    BenchRow,
    _result,
    mcnemar,
    select_methods,
    wilson_ci,
)


def _row(ipo_id: str, *, label: int, net: float, qib: float, total: float, prob: float) -> BenchRow:
    return BenchRow(ipo_id, date(2024, 1, 1), label, net, qib, total, prob)


def test_wilson_ci_bounds() -> None:
    lo, hi = wilson_ci(8, 10)
    assert 0.0 <= lo < 0.8 < hi <= 1.0
    assert wilson_ci(0, 0) == (0.0, 0.0)
    # A unanimous sample still has a finite lower bound (not 1.0).
    lo_all, hi_all = wilson_ci(10, 10)
    assert lo_all < 1.0 and hi_all == 1.0


def test_selectors_and_equal_selectivity() -> None:
    rows = [
        _row("a", label=1, net=0.5, qib=50, total=40, prob=0.9),
        _row("b", label=0, net=-0.1, qib=30, total=20, prob=0.7),
        _row("c", label=1, net=0.2, qib=0.8, total=1.5, prob=0.4),
        _row("d", label=0, net=-0.2, qib=0.5, total=0.6, prob=0.2),
    ]
    sel = select_methods(rows, apply_cutoff=0.65)
    assert {r.ipo_id for r in sel["model_apply"]} == {"a", "b"}  # prob >= 0.65
    assert len(sel["top_n_qib"]) == len(sel["model_apply"])  # equal selectivity
    assert {r.ipo_id for r in sel["top_n_qib"]} == {"a", "b"}  # highest QIB
    assert {r.ipo_id for r in sel["qib_gt_1x"]} == {"a", "b"}  # QIB > 1x
    assert {r.ipo_id for r in sel["total_gt_1x"]} == {"a", "b", "c"}  # total > 1x


def test_result_precision_and_losses() -> None:
    rows = [
        _row("a", label=1, net=0.5, qib=50, total=40, prob=0.9),
        _row("b", label=0, net=-0.2, qib=30, total=20, prob=0.7),
    ]
    res = _result("model_apply", rows)
    assert res.precision == pytest.approx(0.5)
    assert res.n_flops == 1
    assert res.mean_flop_net == pytest.approx(-0.2)
    assert res.worst_flop_net == pytest.approx(-0.2)


def test_mcnemar_disagreements() -> None:
    rows = [
        _row("a", label=1, net=0.5, qib=50, total=40, prob=0.9),
        _row("b", label=0, net=-0.2, qib=30, total=20, prob=0.7),
    ]
    a_only = [rows[0]]  # picks a winner
    b_only = [rows[1]]  # picks a loser
    pair = mcnemar(a_only, b_only, rows)
    assert pair["only_a_picks_winners"] == 1
    assert pair["only_b_picks_losers"] == 1
