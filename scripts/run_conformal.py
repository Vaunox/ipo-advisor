"""Fit + validate the conformal uncertainty bands (v2 B8 Idea 1); persist models/conformal.json.

Builds the walk-forward out-of-sample ``(p̂, y, market_regime)`` points on the 358-IPO backfill,
fits the normalized split-conformal quantile, validates coverage on held-out splits (the B8 gate
— claimed vs realized), and persists the bands next to the calibrator. The regime is computed
exactly as the engine does at serving (Nifty trend + add-only India-VIX stress), so the fitted
band uses the same familiarity axis the live path will.

Read-only w.r.t. the score: this is a layer on top of the gated calibrator's output; it never
refits or touches the calibrator.

Usage:
    python scripts/run_conformal.py [--env dev|prod] [--coverage 0.8] [--k 25]
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from ipo.calibration.benchmark import load_oos_rows
from ipo.calibration.conformal import coverage_report, fit_conformal_bands, save_conformal
from ipo.calibration.dataset import load_records_from_csv
from ipo.calibration.regime import NiftyRegime, VixSeries
from ipo.core.config import RegimeFeatureConfig, load_config
from ipo.features.regime import compute_regime
from ipo.model.scorer import WeightedScorer

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _regime_at(
    day: date, nifty: NiftyRegime, vix: VixSeries | None, rc: RegimeFeatureConfig
) -> float | None:
    """Point-in-time market_regime — identical to VerdictEngine._market_regime_at (add-only VIX)."""
    trend = nifty.market_regime_feature(day)
    if trend is None or vix is None:
        return trend
    stress = vix.vol_stress_at(day)
    if stress is None:
        return trend
    return compute_regime(
        trend, max(0.0, stress), trend_weight=rc.trend_weight, vol_weight=rc.vol_weight
    )


def main() -> None:
    """Fit the conformal bands, report coverage, and persist models/conformal.json."""
    parser = argparse.ArgumentParser(description="Fit + validate conformal uncertainty bands (B8).")
    parser.add_argument("--env", default=None)
    parser.add_argument("--csv", default="data/backfill/mainboard_ipos.csv")
    parser.add_argument("--coverage", type=float, default=0.8)
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
    records = {r.ipo_id: r for r in load_records_from_csv(_REPO_ROOT / args.csv)}
    rc = config.features.regime
    nifty = NiftyRegime(_REPO_ROOT / "data" / "backfill" / "nifty.csv")
    vix_path = _REPO_ROOT / "data" / "backfill" / "vix.csv"
    vix = (
        VixSeries(vix_path, reference=rc.vix_reference, scale=rc.vix_scale)
        if vix_path.is_file()
        else None
    )

    triples = [
        (r.model_prob, r.label, _regime_at(records[r.ipo_id].close_date, nifty, vix, rc), r)
        for r in rows
    ]
    triples = [t for t in triples if t[2] is not None]
    probs = [t[0] for t in triples]
    labels = [t[1] for t in triples]
    regimes = [float(t[2]) for t in triples]  # type: ignore[arg-type]

    rep = coverage_report(probs, labels, regimes, coverage=args.coverage)
    bands = fit_conformal_bands(probs, labels, regimes, coverage=args.coverage)
    save_conformal(bands, _REPO_ROOT / "models" / "conformal.json")

    lines = [
        f"conformal bands (B8 Idea 1) — N={rep.n} OOS, rate-coverage target {args.coverage:.0%}",
        f"  GATE — rate-coverage (band contains true local rate): claimed {rep.claimed:.0%}  "
        f"realized {rep.realized:.0%}  (mean width {rep.mean_width:.2f})",
    ]
    # A few concrete examples: tightest (familiar/confident) vs widest (cold/uncertain).
    examples = sorted(
        (
            (bands.band(t[0], regimes[i]), t[0], regimes[i], t[3].ipo_id)
            for i, t in enumerate(triples)
        ),
        key=lambda e: e[0][1] - e[0][0],
    )
    lines.append("  narrowest (familiar/confident):")
    for (lo, hi), p, reg, ipo in examples[:3]:
        lines.append(f"    {ipo:26} p={p:.0%} regime={reg:+.2f} -> [{lo:.0%}, {hi:.0%}]")
    lines.append("  widest (cold/uncertain):")
    for (lo, hi), p, reg, ipo in examples[-3:]:
        lines.append(f"    {ipo:26} p={p:.0%} regime={reg:+.2f} -> [{lo:.0%}, {hi:.0%}]")
    print("\n".join(lines))  # noqa: T201


if __name__ == "__main__":
    main()
