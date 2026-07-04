"""Recalibration reproducibility check (A4 — GATE A4 clause 2).

Re-runs the Phase-4 calibration fit from the backfill and compares the result to the
shipped ``models/calibrator.json`` **without writing anything**. This is the operate-phase
guard behind "a dry-run recalibration reproduces the current calibrator": the Platt fit is
deterministic, so a faithful re-fit must land on the same parameters. A MISMATCH means the
shipped calibrator is stale versus the current data/code and should be regenerated with
``scripts/run_calibrate.py``.

Read-only: it never overwrites the calibrator or the report. Run it after a quarterly
recalibration to confirm the ritual is reproducible.

Usage:
    python scripts/run_recalibration_check.py [--env dev|prod] [--csv PATH]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ipo.calibration.backtest import evaluate_gate, look_ahead_auc, walk_forward
from ipo.calibration.calibrate import load_calibrator, make_calibrator
from ipo.calibration.dataset import load_records_from_csv, scored_items_from_records
from ipo.core.config import load_config
from ipo.model.scorer import WeightedScorer

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TOL = 1e-9


def _max_param_delta(
    fresh: dict[str, float] | dict[str, list[float]],
    shipped: dict[str, float] | dict[str, list[float]],
) -> float | None:
    """Largest absolute per-parameter difference, or None if the shapes disagree."""
    if set(fresh) != set(shipped):
        return None
    worst = 0.0
    for key in fresh:
        a, b = fresh[key], shipped[key]
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                return None
            worst = max([worst, *(abs(x - y) for x, y in zip(a, b, strict=True))])
        elif isinstance(a, float) and isinstance(b, float):
            worst = max(worst, abs(a - b))
        else:
            return None
    return worst


def main() -> None:
    """Re-fit from the backfill and report whether it reproduces the shipped calibrator."""
    parser = argparse.ArgumentParser(description="Verify recalibration reproduces the calibrator.")
    parser.add_argument("--env", default=None)
    parser.add_argument("--csv", default="data/backfill/mainboard_ipos.csv")
    args = parser.parse_args()

    calib_path = _REPO_ROOT / "models" / "calibrator.json"
    if not calib_path.is_file():
        print(f"[MISSING] no calibrator at {calib_path} to compare against")  # noqa: T201
        raise SystemExit(1)

    config = load_config(env=args.env)
    cal = config.calibration
    records = load_records_from_csv(_REPO_ROOT / args.csv)
    items = scored_items_from_records(
        records,
        WeightedScorer(config.feature_weights, config.features),
        features_config=config.features,
        sell_costs=config.sell_costs,
        nominal_application_value=cal.nominal_application_value,
    )
    rows = walk_forward(
        items, cal.method, initial=cal.walk_forward_initial, step=cal.walk_forward_step
    )
    shuffled = look_ahead_auc(
        items,
        cal.method,
        initial=cal.walk_forward_initial,
        step=cal.walk_forward_step,
        seed=cal.random_seed,
    )
    gate = evaluate_gate(
        rows, config=cal, apply_cutoff=config.verdict_thresholds.apply, shuffled_auc=shuffled
    )
    fresh = make_calibrator(cal.method)
    fresh.fit([it.score for it in items], [it.label for it in items])
    fresh.set_gate(gate.passed)

    shipped = load_calibrator(calib_path)
    delta = _max_param_delta(fresh.params(), shipped.params())
    params_match = delta is not None and delta <= _TOL
    gate_match = fresh.passes_reliability_gate == shipped.passes_reliability_gate
    reproduces = params_match and gate_match

    print(
        f"recalibration dry-run vs {calib_path.name} ({cal.method}, N={len(items)}):"
    )  # noqa: T201
    print(f"  params match: {'yes' if params_match else 'NO'} (max delta {delta})")  # noqa: T201
    print(f"  gate flag match: {'yes' if gate_match else 'NO'}")  # noqa: T201
    if reproduces:
        print("result: REPRODUCES - the recalibration ritual is deterministic")  # noqa: T201
    else:
        print(
            "result: MISMATCH - shipped calibrator is stale vs current data/code; re-run "  # noqa: T201
            "scripts/run_calibrate.py"
        )
    raise SystemExit(0 if reproduces else 1)


if __name__ == "__main__":
    main()
