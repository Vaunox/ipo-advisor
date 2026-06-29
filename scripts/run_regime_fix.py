"""Wire in market_regime and measure the fix OUT-OF-SAMPLE (the operator's constraints).

Compares, on the same walk-forward OOS folds: the official-only model (baseline) vs a
single **regime-aware** model (Nifty market_regime added as a point-in-time feature).
The regime feature is a deterministic transform of past Nifty (no fitting); the
calibrator is fit on past folds only — so this measures generalization, not fit. The
regime-feature weight is the config prior (0.10), NOT tuned to the cold slice.

If the single regime-aware model's cold ECE still does not converge, falls back to
**per-regime calibration** (separate calibrators fit on past cold / past hot folds) and
prints the per-regime fold sizes so their thinness is visible. H1 2022 is shown as a
flagged-but-uninformative sub-row (N=12); nothing is tuned to it.

Usage:
    python scripts/run_regime_fix.py [--env dev] [--csv PATH] [--nifty PATH]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from ipo.calibration.backtest import BacktestRow, ScoredItem, walk_forward
from ipo.calibration.benchmark import wilson_ci
from ipo.calibration.calibrate import make_calibrator
from ipo.calibration.dataset import load_records_from_csv
from ipo.calibration.label import is_positive, net_listing_return
from ipo.calibration.regime import NiftyRegime
from ipo.calibration.reliability import evaluate_reliability
from ipo.core.config import load_config
from ipo.core.constants import IST
from ipo.core.types import Segment
from ipo.features.build import build_features
from ipo.model.scorer import WeightedScorer

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MIN_REGIME_FOLD = 20  # below this, a per-regime calibrator is too thin -> pool


@dataclass(frozen=True)
class Slice:
    """ECE + APPLY precision for one regime slice of OOS rows."""

    n: int
    ece: float
    n_apply: int
    apply_precision: float | None
    ci: tuple[float, float]


def _slice(rows: list[BacktestRow], cutoff: float, n_bins: int) -> Slice:
    if not rows:
        return Slice(0, 0.0, 0, None, (0.0, 0.0))
    rep = evaluate_reliability([r.prob for r in rows], [r.label for r in rows], n_bins)
    applied = [r for r in rows if r.prob >= cutoff]
    pos = sum(r.label for r in applied)
    return Slice(
        n=len(rows),
        ece=rep.ece,
        n_apply=len(applied),
        apply_precision=(pos / len(applied) if applied else None),
        ci=wilson_ci(pos, len(applied)),
    )


def _walk_forward_per_regime(
    items: list[ScoredItem],
    cold_at_decision: dict[str, bool],
    method: str,
    *,
    initial: int,
    step: int,
) -> tuple[list[BacktestRow], list[int]]:
    """Walk-forward with a separate calibrator per regime, selected by decision-time regime.

    For each test block, fit one calibrator on the *past cold* IPOs and one on the *past
    hot* IPOs; predict each test IPO with the calibrator for its (point-in-time) regime.
    Falls back to the pooled calibrator when a regime fold is below ``_MIN_REGIME_FOLD``.
    Returns the rows and the per-block cold-fold sizes (so thinness is visible).
    """
    ordered = sorted(items, key=lambda it: it.listing_date)
    rows: list[BacktestRow] = []
    cold_fold_sizes: list[int] = []
    start = initial
    while start < len(ordered):
        train = ordered[:start]
        test = ordered[start : start + step]
        cold_tr = [t for t in train if cold_at_decision.get(t.ipo_id, False)]
        hot_tr = [t for t in train if not cold_at_decision.get(t.ipo_id, False)]
        cold_fold_sizes.append(len(cold_tr))

        pooled = make_calibrator(method)
        pooled.fit([t.score for t in train], [t.label for t in train])
        cold_cal = None
        if len(cold_tr) >= _MIN_REGIME_FOLD:
            cold_cal = make_calibrator(method)
            cold_cal.fit([t.score for t in cold_tr], [t.label for t in cold_tr])
        hot_cal = None
        if len(hot_tr) >= _MIN_REGIME_FOLD:
            hot_cal = make_calibrator(method)
            hot_cal.fit([t.score for t in hot_tr], [t.label for t in hot_tr])

        for t in test:
            is_cold = cold_at_decision.get(t.ipo_id, False)
            cal = (cold_cal if is_cold else hot_cal) or pooled
            rows.append(
                BacktestRow(t.ipo_id, t.listing_date, t.score, cal.predict_proba(t.score), t.label)
            )
        start += step
    return rows, cold_fold_sizes


def main() -> None:
    """Build baseline + regime-aware models, compare OOS, fall back to per-regime if needed."""
    parser = argparse.ArgumentParser(description="Wire in market_regime and measure OOS.")
    parser.add_argument("--env", default=None)
    parser.add_argument("--csv", default="data/backfill/mainboard_ipos_2017.csv")
    parser.add_argument("--nifty", default="data/backfill/nifty.csv")
    parser.add_argument("--out", default="docs/REGIME_FIX.md")
    args = parser.parse_args()

    config = load_config(env=args.env)
    cal = config.calibration
    cutoff = config.verdict_thresholds.apply
    tol = cal.reliability_tolerance
    scorer = WeightedScorer(config.feature_weights, config.features)
    regime = NiftyRegime(_REPO_ROOT / args.nifty)

    records = load_records_from_csv(_REPO_ROOT / args.csv)
    base_items: list[ScoredItem] = []
    reg_items: list[ScoredItem] = []
    cold_at_decision: dict[str, bool] = {}
    for rec in records:
        if rec.segment is not Segment.MAINBOARD or rec.qib_sub is None or rec.listing_open is None:
            continue
        if rec.listing_date is None:
            continue
        asof = datetime(
            rec.close_date.year, rec.close_date.month, rec.close_date.day, 18, tzinfo=IST
        )
        mr = regime.market_regime_feature(rec.close_date)  # point-in-time, decision-time
        label = is_positive(
            net_listing_return(
                rec.issue_price,
                rec.listing_open,
                config.sell_costs,
                nominal_application_value=cal.nominal_application_value,
            )
        )
        base_feats = build_features(rec, asof, config=config.features)
        reg_feats = build_features(rec, asof, market_regime=mr, config=config.features)
        base_items.append(ScoredItem(rec.ipo_id, rec.listing_date, scorer.score(base_feats), label))
        reg_items.append(ScoredItem(rec.ipo_id, rec.listing_date, scorer.score(reg_feats), label))
        cold_at_decision[rec.ipo_id] = regime.is_cold(rec.close_date)

    base_rows = walk_forward(
        base_items, cal.method, initial=cal.walk_forward_initial, step=cal.walk_forward_step
    )
    reg_rows = walk_forward(
        reg_items, cal.method, initial=cal.walk_forward_initial, step=cal.walk_forward_step
    )

    def cold_hot(rows: list[BacktestRow]) -> tuple[list[BacktestRow], list[BacktestRow]]:
        cold = [r for r in rows if regime.is_cold(r.listing_date)]
        hot = [r for r in rows if not regime.is_cold(r.listing_date)]
        return cold, hot

    base_cold, base_hot = cold_hot(base_rows)
    reg_cold, reg_hot = cold_hot(reg_rows)
    b_cold, a_cold = _slice(base_cold, cutoff, cal.n_buckets), _slice(
        reg_cold, cutoff, cal.n_buckets
    )
    b_hot, a_hot = _slice(base_hot, cutoff, cal.n_buckets), _slice(reg_hot, cutoff, cal.n_buckets)

    # Per-regime fallback only if the single regime-aware model's cold ECE still fails.
    per_regime: Slice | None = None
    cold_folds: list[int] = []
    if a_cold.ece > tol:
        pr_rows, cold_folds = _walk_forward_per_regime(
            reg_items,
            cold_at_decision,
            cal.method,
            initial=cal.walk_forward_initial,
            step=cal.walk_forward_step,
        )
        per_regime = _slice(
            [r for r in pr_rows if regime.is_cold(r.listing_date)], cutoff, cal.n_buckets
        )

    h1 = _slice(
        [r for r in reg_rows if date(2022, 1, 1) <= r.listing_date <= date(2022, 6, 30)],
        cutoff,
        cal.n_buckets,
    )

    lines = _report(b_cold, a_cold, b_hot, a_hot, per_regime, cold_folds, h1, tol, cutoff)
    (_REPO_ROOT / args.out).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))  # noqa: T201


def _report(
    b_cold: Slice,
    a_cold: Slice,
    b_hot: Slice,
    a_hot: Slice,
    per_regime: Slice | None,
    cold_folds: list[int],
    h1: Slice,
    tol: float,
    cutoff: float,
) -> list[str]:
    def p(s: Slice) -> str:
        prec = "n/a" if s.apply_precision is None else f"{s.apply_precision:.0%}"
        return f"{prec} [{s.ci[0]:.0%},{s.ci[1]:.0%}] (N={s.n}, APPLY={s.n_apply})"

    single_ok = a_cold.ece <= tol
    if single_ok:
        outcome = "Single regime-aware model CONVERGED the cold ECE."
    elif per_regime is not None and per_regime.ece <= tol and per_regime.n_apply > 0:
        outcome = "Single model insufficient; PER-REGIME calibration converged the cold ECE."
    else:
        outcome = (
            "Cold probability STILL does not calibrate. Correct outcome: GATE/FLAG APPLY as "
            "'cold-market — ranking reliable, probability less certain'; do not force the number."
        )

    lines = [
        "# Regime Fix — wiring in market_regime, measured out-of-sample",
        "",
        "*Walk-forward OOS only: the regime feature is a deterministic transform of past "
        "Nifty (no fit); the calibrator is fit on past folds; the regime weight is the "
        f"config prior (0.10), not tuned to the cold slice. ECE tolerance = {tol}. "
        "Not financial advice.*",
        "",
        "## Cold slice — before vs after (the question)",
        "",
        "| Metric | Before (official-only) | After (regime-aware) |",
        "|---|---|---|",
        f"| Cold ECE | {b_cold.ece:.3f} | **{a_cold.ece:.3f}** |",
        f"| Cold APPLY precision | {p(b_cold)} | {p(a_cold)} |",
        "",
        "## Hot slice — sanity (should not break)",
        "",
        "| Metric | Before | After |",
        "|---|---|---|",
        f"| Hot ECE | {b_hot.ece:.3f} | {a_hot.ece:.3f} |",
        f"| Hot APPLY precision | {p(b_hot)} | {p(a_hot)} |",
        "",
    ]
    if per_regime is not None:
        thin = [n for n in cold_folds if n < _MIN_REGIME_FOLD]
        lines += [
            "## Per-regime calibration (fallback — single model didn't converge cold)",
            "",
            f"- Cold ECE (per-regime calibrators): **{per_regime.ece:.3f}** | "
            f"cold APPLY {p(per_regime)}",
            f"- Per-block **cold training-fold sizes**: {cold_folds} "
            f"(min usable = {_MIN_REGIME_FOLD}; {len(thin)} blocks fell back to pooled).",
            "- A cold fold below ~20 can't calibrate a separate curve — judge from those Ns.",
            "",
        ]
    lines += [
        f"## H1 2022 (flagged, uninformative — N={h1.n}, not tuned to)",
        "",
        f"- Cold-correction sub-period: ECE {h1.ece:.3f}, APPLY {p(h1)}. Too thin to read.",
        "",
        "## Outcome",
        "",
        f"**{outcome}**",
        "",
        "The *ranking* edge was already regime-robust (cold APPLY precision well above the "
        "cold base rate). This step is purely about whether the *probability* calibrates in "
        "cold markets out-of-sample. APPLY cutoff = config "
        f"{cutoff}; nothing was tuned to the reported slice.",
    ]
    return lines


if __name__ == "__main__":
    main()
