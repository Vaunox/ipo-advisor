"""Regime stress-test: does the model's edge survive cold markets? (Phase-4 discipline).

Segments the walk-forward out-of-sample IPOs by the Nifty regime at listing (cold =
negative 3-month trend or drawdown) and reports, per regime: N, AUC, ECE, the
calibration curve, and APPLY precision **vs that regime's own base rate**. The
threshold is the config product decision (not chosen on any reported slice); the
model's probabilities are the untouched walk-forward ones. Nothing is tuned.

Usage:
    python scripts/run_regime_test.py [--env dev] [--csv PATH] [--nifty PATH] [--label STAGE]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ipo.calibration.benchmark import BenchRow, load_oos_rows, wilson_ci
from ipo.calibration.regime import NiftyRegime
from ipo.calibration.reliability import evaluate_reliability
from ipo.core.config import load_config
from ipo.model.scorer import WeightedScorer

_REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RegimeRow:
    """Per-regime metrics for the report."""

    name: str
    n: int
    base_rate: float
    auc: float
    ece: float
    n_apply: int
    apply_precision: float | None
    ci_low: float
    ci_high: float
    bucket70_obs: float | None
    bucket70_n: int


def _metrics(name: str, rows: list[BenchRow], cutoff: float, n_bins: int) -> RegimeRow:
    if not rows:
        return RegimeRow(name, 0, 0.0, 0.0, 0.0, 0, None, 0.0, 0.0, None, 0)
    probs = [r.model_prob for r in rows]
    labels = [r.label for r in rows]
    rep = evaluate_reliability(probs, labels, n_bins)
    applied = [r for r in rows if r.model_prob >= cutoff]
    pos = sum(r.label for r in applied)
    lo, hi = wilson_ci(pos, len(applied))
    # "Does a 70% stay ~70%?" -> the calibration bin straddling 0.7.
    near = [b for b in rep.bins if 0.65 <= b.mean_predicted < 0.80]
    b70_obs = (
        sum(b.observed_rate * b.count for b in near) / sum(b.count for b in near) if near else None
    )
    b70_n = sum(b.count for b in near)
    return RegimeRow(
        name=name,
        n=len(rows),
        base_rate=rep.base_rate,
        auc=rep.auc,
        ece=rep.ece,
        n_apply=len(applied),
        apply_precision=(pos / len(applied) if applied else None),
        ci_low=lo,
        ci_high=hi,
        bucket70_obs=b70_obs,
        bucket70_n=b70_n,
    )


def main() -> None:
    """Run the regime stress-test and write the report."""
    parser = argparse.ArgumentParser(description="Regime stress-test of the calibrated model.")
    parser.add_argument("--env", default=None)
    parser.add_argument("--csv", default="data/backfill/mainboard_ipos.csv")
    parser.add_argument("--nifty", default="data/backfill/nifty.csv")
    parser.add_argument("--label", default="Stage 1 (existing 2021+ sample)")
    parser.add_argument("--out", default="docs/REGIME_STRESS.md")
    args = parser.parse_args()

    config = load_config(env=args.env)
    cal = config.calibration
    cutoff = config.verdict_thresholds.apply
    scorer = WeightedScorer(config.feature_weights, config.features)

    rows = load_oos_rows(
        _REPO_ROOT / args.csv,
        scorer=scorer,
        features_config=config.features,
        sell_costs=config.sell_costs,
        nominal_application_value=cal.nominal_application_value,
        method=cal.method,
        initial=cal.walk_forward_initial,
        step=cal.walk_forward_step,
    )
    regime = NiftyRegime(_REPO_ROOT / args.nifty)

    classified = [(r, regime.regime_at(r.listing_date)) for r in rows]
    cold = [r for r, info in classified if info.is_cold]
    hot = [r for r, info in classified if not info.is_cold]
    h1_2022 = [r for r in rows if date(2022, 1, 1) <= r.listing_date <= date(2022, 6, 30)]

    groups = [
        _metrics("All (overall)", rows, cutoff, cal.n_buckets),
        _metrics("Hot (Nifty up 3m)", hot, cutoff, cal.n_buckets),
        _metrics("Cold (neg 3m trend / drawdown)", cold, cutoff, cal.n_buckets),
        _metrics("Cold sub-period: H1 2022", h1_2022, cutoff, cal.n_buckets),
    ]

    lines = _report(args.label, groups, cutoff, len(rows), len(cold))
    (_REPO_ROOT / args.out).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))  # noqa: T201


def _report(label: str, groups: list[RegimeRow], cutoff: float, n: int, n_cold: int) -> list[str]:
    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{x:.0%}"

    lines = [
        "# Regime Stress-Test — does the edge survive cold markets?",
        "",
        f"*{label}. Walk-forward OOS, threshold = config {cutoff} (not chosen on any "
        "reported slice). Cold = Nifty negative 3-month trend or drawdown at listing. "
        "Not financial advice.*",
        "",
        f"Out-of-sample IPOs: **{n}** | cold: **{n_cold}** | hot: **{n - n_cold}**",
        "",
        "| Regime | N | Base | AUC | ECE | APPLY N | APPLY prec | 95% CI | ~70% obs/N |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for g in groups:
        if g.n == 0:
            lines.append(
                f"| {g.name} | 0 | — | — | — | — | — | — | (no OOS rows; in training window) |"
            )
            continue
        lines.append(
            f"| {g.name} | {g.n} | {g.base_rate:.0%} | {g.auc:.2f} | {g.ece:.3f} | "
            f"{g.n_apply} | {pct(g.apply_precision)} | [{g.ci_low:.0%}, {g.ci_high:.0%}] | "
            f"{pct(g.bucket70_obs)} / {g.bucket70_n} |"
        )
    cold_row = next(g for g in groups if g.name.startswith("Cold (neg"))
    beats = cold_row.apply_precision is not None and cold_row.apply_precision > cold_row.base_rate
    lines += [
        "",
        "## Plain reading (cold slice)",
        "",
        f"- **APPLY vs base rate (cold):** APPLY precision {pct(cold_row.apply_precision)} "
        f"vs cold base rate {cold_row.base_rate:.0%} — "
        + ("**still beats** the base rate." if beats else "**does NOT beat** the base rate."),
        f"- **Does a 70% stay ~70% (cold)?** the ~70% bucket lists positive "
        f"{pct(cold_row.bucket70_obs)} over N={cold_row.bucket70_n} "
        + ("(thin — read with caution)." if cold_row.bucket70_n < 15 else "."),
        f"- **Discrimination (cold):** AUC {cold_row.auc:.2f} "
        + ("(holds)." if cold_row.auc >= 0.6 else "(weakened vs hot)."),
        "",
        "*Per-bucket Ns are shown so thin cells are visible. If APPLY precision in the "
        "cold slice collapses toward its base rate, the edge is regime-dependent and "
        "APPLY should be gated on the market-regime feature rather than hidden.*",
    ]
    return lines


if __name__ == "__main__":
    main()
