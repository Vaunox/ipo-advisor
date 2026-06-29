"""Phase 4 driver: backtest -> calibrate -> reliability gate -> persist + report.

Loads the backfilled mainboard sample, reconstructs as-of features (GMP absent by
design until Phase 5), scores them, derives the net-of-cost label, runs the
walk-forward backtest, evaluates the reliability gate (plus the look-ahead shuffle),
fits and persists the final calibrator with its provenance, and writes
``docs/CALIBRATION.md``. The calibrator's gate flag is set ONLY if the gate passes —
Layer 3 keeps withholding probabilities otherwise (Inviolable Rule 1).

Usage:
    python scripts/run_calibrate.py [--env dev|prod] [--csv PATH]
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from ipo.calibration.backtest import evaluate_gate, look_ahead_auc, walk_forward
from ipo.calibration.calibrate import (
    CalibratorMeta,
    feature_code_hash,
    make_calibrator,
    save_calibrator,
)
from ipo.calibration.dataset import load_records_from_csv, scored_items_from_records
from ipo.core.config import load_config
from ipo.core.constants import IST
from ipo.core.logging import configure_logging, get_logger
from ipo.features.build import build_features
from ipo.features.leakage import is_point_in_time_safe
from ipo.model.scorer import WeightedScorer

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LABEL_DEF = "net_of_cost(listing_open) > 0"


def main() -> None:
    """Run the full Phase-4 calibration and write the report + persisted calibrator."""
    parser = argparse.ArgumentParser(description="Fit + gate the calibrator (Phase 4).")
    parser.add_argument("--env", default=None)
    parser.add_argument("--csv", default="data/backfill/mainboard_ipos.csv")
    args = parser.parse_args()

    config = load_config(env=args.env)
    configure_logging(config.logging.level, json_output=config.logging.json_output)
    log = get_logger("ipo.scripts.run_calibrate")
    cal_cfg = config.calibration

    records = load_records_from_csv(_REPO_ROOT / args.csv)
    scorer = WeightedScorer(config.feature_weights, config.features)

    # Leakage firewall on a sample before trusting any score (Deep Dive #4 §B).
    sample = next((r for r in records if r.listing_open is not None), None)
    if sample is not None:
        asof = datetime(
            sample.close_date.year, sample.close_date.month, sample.close_date.day, 18, tzinfo=IST
        )
        if not is_point_in_time_safe(
            lambda r, a: build_features(r, a, config=config.features), sample, asof
        ):
            raise SystemExit("LEAKAGE DETECTED: features depend on post-decision data. Aborting.")

    items = scored_items_from_records(
        records,
        scorer,
        features_config=config.features,
        sell_costs=config.sell_costs,
        nominal_application_value=cal_cfg.nominal_application_value,
    )
    log.info("calibration_sample", extra={"scored": len(items), "loaded": len(records)})
    if len(items) < cal_cfg.min_training_samples:
        log.warning(
            "below_min_samples",
            extra={"have": len(items), "need": cal_cfg.min_training_samples},
        )

    rows = walk_forward(
        items, cal_cfg.method, initial=cal_cfg.walk_forward_initial, step=cal_cfg.walk_forward_step
    )
    shuffled = look_ahead_auc(
        items,
        cal_cfg.method,
        initial=cal_cfg.walk_forward_initial,
        step=cal_cfg.walk_forward_step,
        seed=cal_cfg.random_seed,
    )
    gate = evaluate_gate(
        rows, config=cal_cfg, apply_cutoff=config.verdict_thresholds.apply, shuffled_auc=shuffled
    )

    # Fit the final calibrator on all data; the gate flag governs whether it may ship.
    calibrator = make_calibrator(cal_cfg.method)
    calibrator.fit([it.score for it in items], [it.label for it in items])
    calibrator.set_gate(gate.passed)
    meta = CalibratorMeta(
        feature_code_hash=feature_code_hash(
            (_REPO_ROOT / "src/ipo/features/build.py").read_text(encoding="utf-8"),
            (_REPO_ROOT / "src/ipo/model/scorer.py").read_text(encoding="utf-8"),
        ),
        label_definition=_LABEL_DEF,
        sample_size=len(items),
        base_rate=gate.report.base_rate,
    )
    save_calibrator(calibrator, _REPO_ROOT / "models" / "calibrator.json", meta=meta)
    _write_report(
        _REPO_ROOT / "docs" / "CALIBRATION.md",
        gate,
        meta,
        cal_cfg.method,
        config.verdict_thresholds.apply,
    )

    verdict = "PASSED" if gate.passed else "NOT PASSED (probabilities stay withheld)"
    print(f"Calibration gate: {verdict}")  # noqa: T201
    for c in gate.checks:
        print(f"  [{'PASS' if c.passed else 'FAIL'}] {c.name}: {c.detail}")  # noqa: T201


def _write_report(path: Path, gate: object, meta: object, method: str, apply_cutoff: float) -> None:
    from ipo.calibration.backtest import GateResult
    from ipo.calibration.calibrate import CalibratorMeta

    assert isinstance(gate, GateResult)
    assert isinstance(meta, CalibratorMeta)
    r = gate.report
    lines = [
        "# Calibration Report (Phase 4)",
        "",
        "*The artifact that earns the right to show probabilities. Official-only model "
        "(GMP added in Phase 5). This is an engineering/research reference, not financial advice.*",
        "",
        f"- **Calibrator:** {method} | feature-code hash `{meta.feature_code_hash}`",
        f"- **Label definition:** `{meta.label_definition}`",
        f"- **Sample size (scored, OOS-eligible):** {meta.sample_size}",
        f"- **Base rate (positive net listing):** {r.base_rate:.1%}",
        f"- **OOS AUC:** {r.auc:.3f} | **ECE:** {r.ece:.3f} | **Brier:** {r.brier:.3f}",
        f"- **APPLY precision (cutoff {apply_cutoff}):** "
        + (
            f"{gate.apply_precision:.1%}" if gate.apply_precision is not None else "n/a (no APPLYs)"
        ),
        f"- **Look-ahead shuffled AUC:** {gate.look_ahead_auc:.3f} (must be ~0.5)",
        "",
        f"## Reliability gate: {'PASSED' if gate.passed else 'NOT PASSED'}",
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
    ]
    lines += [f"| {c.name} | {'PASS' if c.passed else 'FAIL'} | {c.detail} |" for c in gate.checks]
    lines += [
        "",
        "## Reliability diagram (predicted vs observed)",
        "",
        "| Bin mean predicted | Observed rate | Count |",
        "|---|---|---|",
    ]
    lines += [f"| {b.mean_predicted:.2f} | {b.observed_rate:.2f} | {b.count} |" for b in r.bins]
    lines += [
        "",
        "## Honest posture (Deep Dive #4)",
        "",
        f"~{meta.sample_size} mainboard IPOs is a small sample: per-bucket confidence "
        "intervals are wide. State the sample size and base rate next to every "
        "probability; recalibrate quarterly and after regime shifts. A calibrated 70% "
        "still fails ~30% of the time.",
        "",
        "If the gate did not pass, the official-only signal is insufficient on its own "
        "— proceed to Phase 5 (GMP) and re-evaluate; until then Layer 3 shows the "
        "verdict with the uncalibrated banner and withholds the probability.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
