"""Export the walk-forward out-of-sample reliability report as machine-readable JSON.

The API's ``/calibration`` serves the **held-out** reliability (predicted vs observed per bucket,
plus ECE / Brier / AUC / base rate) so the History reliability diagram shows the honest calibration
— never an in-sample recompute (Inviolable Rule 1). This regenerates that report from the *same*
walk-forward pipeline that sets the reliability gate and writes ``models/reliability.json``,
versioned alongside the calibrator.

Usage:
    python scripts/run_reliability_export.py [--env dev|prod] [--csv PATH]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ipo.calibration.benchmark import load_oos_rows
from ipo.calibration.calibrate import load_calibrator
from ipo.calibration.reliability import evaluate_reliability
from ipo.core.config import load_config
from ipo.model.scorer import WeightedScorer

_REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """Run the walk-forward OOS reliability and persist it as models/reliability.json."""
    parser = argparse.ArgumentParser(description="Export held-out reliability report as JSON.")
    parser.add_argument("--env", default=None)
    parser.add_argument("--csv", default="data/backfill/mainboard_ipos.csv")
    args = parser.parse_args()

    config = load_config(env=args.env)
    cal = config.calibration
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
    rel = evaluate_reliability([r.model_prob for r in rows], [r.label for r in rows], cal.n_buckets)
    calibrator = load_calibrator(_REPO_ROOT / "models" / "calibrator.json")

    report = {
        "version": calibrator.version,
        "gate_passed": calibrator.passes_reliability_gate,
        "source": "walk-forward out-of-sample",
        "n": rel.n,
        "base_rate": rel.base_rate,
        "ece": rel.ece,
        "brier": rel.brier,
        "auc": rel.auc,
        "bins": [
            {"mean_predicted": b.mean_predicted, "observed_rate": b.observed_rate, "count": b.count}
            for b in rel.bins
        ],
    }
    out = _REPO_ROOT / "models" / "reliability.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(  # noqa: T201
        f"wrote {out} — n={rel.n} ece={rel.ece:.3f} brier={rel.brier:.3f} "
        f"auc={rel.auc:.3f} bins={len(rel.bins)}"
    )


if __name__ == "__main__":
    main()
