"""Total-only comparison gate — full vs QIB-only vs Total-only (research only, OFF-MAIN).

Runs the **exact** shipped walk-forward methodology (expanding-window Platt calibrator refit
per arm, no random folds) on the 358-IPO calibration set for three arms:

* ``full``       — the shipped scorer (QIB+NII+retail), i.e. the production model;
* ``qib_only``   — the scorer's QIB term alone;
* ``total_only`` — the same subscription normalization on the **total** multiple only.

For each of the three standard 358-sample splits (214/71, 179/53, 143/35 — identical to the
B2/B7 gate tables) it reports OOS AUC and ECE per arm, plus a **paired-bootstrap 95% CI** on
the AUC difference (variant - full), so the format matches every gate table in PROJECT_LOG.md.
The paired bootstrap resamples the OOS IPOs with replacement (same indices for both arms) so
the CI reflects the *within-sample* degradation, not two independent noisy AUCs.

This is a COMPARISON gate, not a promotion: it writes nothing under ``models/`` or ``src/`` and
never mutates the shipped calibrator. Determinism: walk-forward is exact; bootstrap seed = 17.

Usage:
    PYTHONPATH=src python research/run_total_only_gate.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from research.total_only_variant import build_variant_items, load_total_sub_by_id

from ipo.calibration.backtest import (
    BacktestRow,
    ScoredItem,
    evaluate_gate,
    look_ahead_auc,
    walk_forward,
)
from ipo.calibration.dataset import load_records_from_csv, scored_items_from_records
from ipo.calibration.reliability import auc_score, evaluate_reliability
from ipo.core.config import load_config
from ipo.model.scorer import WeightedScorer

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CSV = _REPO_ROOT / "data" / "backfill" / "mainboard_ipos.csv"
_SPLITS = [(214, 71), (179, 53), (143, 35)]  # same 3 splits as the B2/B7 358-sample gates
_BOOT = 2000
_BOOT_SEED = 17


@dataclass(frozen=True)
class ArmMetrics:
    """OOS metrics for one arm on one split."""

    auc: float
    ece: float
    n: int


def _aligned(rows: list[BacktestRow]) -> dict[str, tuple[float, int]]:
    """Map ipo_id -> (prob, label) so arms can be paired by IPO regardless of row order."""
    return {r.ipo_id: (r.prob, r.label) for r in rows}


def _arm_metrics(rows: list[BacktestRow]) -> ArmMetrics:
    rep = evaluate_reliability([r.prob for r in rows], [r.label for r in rows])
    return ArmMetrics(auc=rep.auc, ece=rep.ece, n=rep.n)


def paired_auc_lift_ci(
    full_rows: list[BacktestRow],
    var_rows: list[BacktestRow],
    *,
    n_boot: int = _BOOT,
    seed: int = _BOOT_SEED,
) -> tuple[float, float, float]:
    """Point estimate and 95% CI for AUC(variant) - AUC(full), paired by IPO.

    Resamples the common OOS IPOs with replacement (identical indices applied to both
    arms) ``n_boot`` times; the CI is the 2.5/97.5 percentiles of the per-resample AUC
    difference. Resamples without both classes present are skipped (AUC undefined).
    """
    full = _aligned(full_rows)
    var = _aligned(var_rows)
    ids = [i for i in full if i in var]
    pf = np.array([full[i][0] for i in ids], dtype=np.float64)
    pv = np.array([var[i][0] for i in ids], dtype=np.float64)
    y = np.array([full[i][1] for i in ids], dtype=np.float64)  # labels identical across arms

    point = auc_score(pv.tolist(), y.astype(int).tolist()) - auc_score(
        pf.tolist(), y.astype(int).tolist()
    )

    rng = np.random.default_rng(seed)
    n = len(ids)
    diffs: list[float] = []
    for _ in range(n_boot):
        samp = rng.integers(0, n, n)
        ys = y[samp]
        if ys.sum() == 0 or ys.sum() == n:
            continue
        a_var = auc_score(pv[samp].tolist(), ys.astype(int).tolist())
        a_full = auc_score(pf[samp].tolist(), ys.astype(int).tolist())
        diffs.append(a_var - a_full)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return float(point), float(lo), float(hi)


def _headline(
    items: list[ScoredItem], method: str, cfg: object
) -> tuple[float, float, float, float]:
    """Default 60/20 walk-forward headline (AUC, ECE, Brier, shuffled) — the §4.1 comparator."""
    initial = cfg.walk_forward_initial  # type: ignore[attr-defined]
    step = cfg.walk_forward_step  # type: ignore[attr-defined]
    seed = cfg.random_seed  # type: ignore[attr-defined]
    rows = walk_forward(items, method, initial=initial, step=step)
    rep = evaluate_reliability([r.prob for r in rows], [r.label for r in rows])
    shuffled = look_ahead_auc(items, method, initial=initial, step=step, seed=seed)
    return rep.auc, rep.ece, rep.brier, shuffled


def main() -> None:
    """Run the comparison gate and print the tables + verdict."""
    config = load_config(env=None)
    cal = config.calibration
    scorer = WeightedScorer(config.feature_weights, config.features)

    records = load_records_from_csv(_CSV)
    full_items = scored_items_from_records(
        records,
        scorer,
        features_config=config.features,
        sell_costs=config.sell_costs,
        nominal_application_value=cal.nominal_application_value,
    )
    totals = load_total_sub_by_id(_CSV)
    qib_items, total_items = build_variant_items(
        full_items, records, scorer=scorer, features_config=config.features, totals=totals
    )
    assert len(qib_items) == len(full_items) == len(total_items) == 358, (
        f"arm membership mismatch: full={len(full_items)} qib={len(qib_items)} "
        f"total={len(total_items)}"
    )

    arms = {"full": full_items, "qib_only": qib_items, "total_only": total_items}

    # --- Headlines (default 60/20 walk-forward — directly comparable to §4.1) ---
    print("=" * 78)
    print("HEADLINE (default 60/20 walk-forward; full reproduces shipped §4.1 = 0.797/0.081)")
    print("=" * 78)
    print(f"{'arm':<12}{'OOS N':>7}{'AUC':>9}{'ECE':>9}{'Brier':>9}{'shuffled':>11}")
    for name, items in arms.items():
        auc, ece, brier, shuf = _headline(items, cal.method, cal)
        print(f"{name:<12}{298:>7}{auc:>9.3f}{ece:>9.3f}{brier:>9.3f}{shuf:>11.3f}")

    # --- Per-split gate tables: each variant vs full ---
    for variant in ("qib_only", "total_only"):
        print()
        print("=" * 78)
        print(f"GATE TABLE — {variant} vs full  (off = full model, on = {variant})")
        print("=" * 78)
        print(
            f"{'split':>10} {'OOS N':>6} {'AUC full->var':>16} {'ECE full->var':>16} "
            f"{'AUC d (95% CI)':>24}"
        )
        for initial, step in _SPLITS:
            full_rows = walk_forward(full_items, cal.method, initial=initial, step=step)
            var_rows = walk_forward(arms[variant], cal.method, initial=initial, step=step)
            fm = _arm_metrics(full_rows)
            vm = _arm_metrics(var_rows)
            point, lo, hi = paired_auc_lift_ci(full_rows, var_rows)
            print(
                f"{f'{initial}/{step}':>10} {fm.n:>6} "
                f"{f'{fm.auc:.3f}->{vm.auc:.3f}':>16} "
                f"{f'{fm.ece:.3f}->{vm.ece:.3f}':>16} "
                f"{f'{point:+.3f} [{lo:+.3f}, {hi:+.3f}]':>24}"
            )

    # --- The SAME six-check reliability gate the shipped model passes, per arm (60/20) ---
    print()
    print("=" * 78)
    print("RELIABILITY GATE (the shipped six checks, default 60/20) — would each arm pass?")
    print("=" * 78)
    for name, items in arms.items():
        rows = walk_forward(
            items, cal.method, initial=cal.walk_forward_initial, step=cal.walk_forward_step
        )
        shuffled = look_ahead_auc(
            items, cal.method, initial=cal.walk_forward_initial, step=cal.walk_forward_step,
            seed=cal.random_seed,
        )
        gate = evaluate_gate(
            rows, config=cal, apply_cutoff=config.verdict_thresholds.apply, shuffled_auc=shuffled
        )
        print(f"\n{name}: {'PASSED' if gate.passed else 'NOT PASSED'}")
        for c in gate.checks:
            print(f"  [{'PASS' if c.passed else 'FAIL'}] {c.name}: {c.detail}")

    print()
    print("Notes: 'AUC d' is variant-minus-full (negative = the reduced model discriminates")
    print("worse). CI is a 2000x paired bootstrap over the OOS IPOs (seed 17). ECE bound 0.10.")


if __name__ == "__main__":
    main()
