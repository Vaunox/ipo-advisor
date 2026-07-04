"""Report calibration stability across the T+3 settlement cutover (A4 part 2).

Loads the walk-forward out-of-sample rows, splits them by the ``t3_regime`` dummy
(mandatory cutover 1 Dec 2023), and reports whether the already-calibrated model behaves
differently pre vs post the break — a read-only check that never refits the calibrator or
adds the dummy to the score. Writes ``docs/T3_STABILITY.md`` and prints a summary.

Usage:
    python scripts/run_t3_stability.py [--env dev|prod] [--csv PATH]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ipo.calibration.benchmark import load_oos_rows
from ipo.core.config import load_config
from ipo.model.scorer import WeightedScorer
from ipo.service.monitoring import AccuracySnapshot
from ipo.service.stability import CrossBreakStability, cross_break_stability

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _precision(snap: AccuracySnapshot) -> str:
    if snap.apply_precision is None:
        return "n/a (no APPLYs)"
    return (
        f"{snap.apply_precision:.0%} "
        f"(95% CI {snap.precision_ci_low:.0%}-{snap.precision_ci_high:.0%}, n={snap.n_apply})"
    )


def _lines(s: CrossBreakStability, *, apply_cutoff: float) -> list[str]:
    return [
        "# T+3 cross-break calibration stability (A4)",
        "",
        "*Does the calibrated model behave differently across the SEBI T+6->T+3 listing-timeline "
        f"cutover (mandatory **{s.cutover.isoformat()}**)? Walk-forward out-of-sample rows, "
        "split by the `t3_regime` dummy. A **read-only reported check** — the dummy is never "
        "added to the score and the calibrator is never refit. Engineering/research reference, "
        "not financial advice.*",
        "",
        f"**Verdict: {s.verdict}**",
        "",
        f"| slice | n | base rate | APPLY precision @ {apply_cutoff:.2f} (95% CI) | ECE |",
        "|---|---|---|---|---|",
        f"| pre-T+3 (< {s.cutover.isoformat()}) | {s.pre.n} | {s.pre.base_rate:.0%} "
        f"| {_precision(s.pre)} | {s.pre.ece:.3f} |",
        f"| post-T+3 (>= {s.cutover.isoformat()}) | {s.post.n} | {s.post.base_rate:.0%} "
        f"| {_precision(s.post)} | {s.post.ece:.3f} |",
        "",
        f"ECE shift across the break: **{s.ece_shift:+.3f}** (tolerance {s.ece_tolerance:.3f}).",
        "",
        "*Honest caveat:* the smaller of the two slices carries the wider confidence interval, "
        "so a STABLE read means no cross-break difference is **detectable** at this sample size, "
        "not that none exists. Re-run as more post-T+3 outcomes accrue; if a real difference "
        "emerges, the action is an operator recalibration on post-cutover data, not a silent "
        "change here.",
    ]


def main() -> None:
    """Compute and report cross-break calibration stability; write docs/T3_STABILITY.md."""
    parser = argparse.ArgumentParser(description="Report calibration stability across T+3.")
    parser.add_argument("--env", default=None)
    parser.add_argument("--csv", default="data/backfill/mainboard_ipos.csv")
    args = parser.parse_args()

    config = load_config(env=args.env)
    cal = config.calibration
    cutoff = config.verdict_thresholds.apply
    rows = load_oos_rows(
        _REPO_ROOT / args.csv,
        scorer=WeightedScorer(config.feature_weights, config.features),
        features_config=config.features,
        sell_costs=config.sell_costs,
        nominal_application_value=cal.nominal_application_value,
        method=cal.method,
        initial=cal.walk_forward_initial,
        step=cal.walk_forward_step,
    )
    stability = cross_break_stability(rows, apply_cutoff=cutoff, n_bins=cal.n_buckets)
    lines = _lines(stability, apply_cutoff=cutoff)
    out = _REPO_ROOT / "docs" / "T3_STABILITY.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[4:6]))  # noqa: T201 — the verdict line
    print(f"\nwrote {out}")  # noqa: T201


if __name__ == "__main__":
    main()
