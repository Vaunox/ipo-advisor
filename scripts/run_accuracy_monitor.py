"""Live verdict-accuracy monitor (A4 — operate-phase hardening).

Compares a recent window of realized IPO outcomes against the walk-forward out-of-sample
baseline the calibrator was gated on, and raises a drift alert only on a *real* departure
(APPLY-precision Wilson interval below baseline, or ECE beyond tolerance). This is an
occasional operator ritual, not a standing daemon — run it after a batch of listings.

The outcome history is the same CSV the model is backfilled/calibrated from; as live IPOs
list, append their realized rows and the "recent window" becomes the genuine live edge.
Exits non-zero when a drift alert fires so it can gate a scheduled check.

Usage:
    python scripts/run_accuracy_monitor.py [--env dev|prod] [--csv PATH]
                                           [--window N] [--ece-tolerance F] [--min-window N]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ipo.calibration.benchmark import load_oos_rows
from ipo.core.config import load_config
from ipo.model.scorer import WeightedScorer
from ipo.service.monitoring import (
    AccuracySnapshot,
    MonitorResult,
    evaluate_drift,
    snapshot_from_rows,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _fmt_precision(snap: AccuracySnapshot) -> str:
    if snap.apply_precision is None:
        return "n/a (no APPLYs)"
    return (
        f"{snap.apply_precision:.0%} "
        f"(95% CI {snap.precision_ci_low:.0%}-{snap.precision_ci_high:.0%}, n_apply={snap.n_apply})"
    )


def _report(result: MonitorResult, *, window_n: int, total_n: int) -> str:
    b, w = result.baseline, result.window
    lines = [
        f"verdict-accuracy monitor - recent {window_n} of {total_n} OOS listings vs baseline",
        f"  APPLY precision:  baseline {_fmt_precision(b)}",
        f"                    recent   {_fmt_precision(w)}",
        f"  ECE:              baseline {b.ece:.3f}   recent {w.ece:.3f}",
        f"  base rate:        baseline {b.base_rate:.0%}   recent {w.base_rate:.0%}",
    ]
    if result.insufficient_sample:
        lines.append(f"result: INCONCLUSIVE - recent window n={w.n} below min-window (not judged)")
    elif result.alerts:
        lines.append(f"result: DRIFT ALERT ({len(result.alerts)})")
        lines += [f"  ! {a}" for a in result.alerts]
    else:
        lines.append("result: OK - no drift")
    return "\n".join(lines)


def main() -> None:
    """Load the OOS rows, snapshot baseline vs recent window, and report any drift."""
    parser = argparse.ArgumentParser(description="Monitor live verdict accuracy vs the backtest.")
    parser.add_argument("--env", default=None)
    parser.add_argument("--csv", default="data/backfill/mainboard_ipos.csv")
    parser.add_argument("--window", type=int, default=60, help="most-recent listings to test")
    parser.add_argument("--ece-tolerance", type=float, default=0.03)
    parser.add_argument("--min-window", type=int, default=20)
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
    rows.sort(key=lambda r: r.listing_date)
    window_rows = rows[-args.window :] if args.window > 0 else rows

    baseline = snapshot_from_rows(rows, apply_cutoff=cutoff, n_bins=cal.n_buckets)
    window = snapshot_from_rows(window_rows, apply_cutoff=cutoff, n_bins=cal.n_buckets)
    result = evaluate_drift(
        baseline, window, ece_tolerance=args.ece_tolerance, min_window=args.min_window
    )

    print(_report(result, window_n=len(window_rows), total_n=len(rows)))  # noqa: T201
    if result.alerts:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
