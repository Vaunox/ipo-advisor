"""Independent regime replication on the skworld Kaggle set (cold-richer, 2010+).

This does NOT feed the official calibrator (its 'Listing Gain' label differs from our
net-of-open label — mixing label definitions is forbidden, Deep Dive #4). Instead it
runs the *same* subscription-driven model + walk-forward + regime segmentation on an
independent dataset that has far more cold-market IPOs (2010–2016, incl. the 2011–13
'IPO winter') to test one thing: does 'cold calibration degrades' replicate, or was it
a small-sample artifact of our 2017+ data?

Reads the skworld CSVs from a local path (gitignored); nothing third-party is committed.
Label: positive if listing gain exceeds an approximate ~0.5% round-trip cost. The model
is subscription-only (QIB/NII/retail), identical to ours.

Usage:
    python scripts/run_skworld_regime.py [--path data_store/_kag] [--nifty data/backfill/nifty.csv]
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
from pathlib import Path

from ipo.calibration.backtest import BacktestRow, ScoredItem, walk_forward
from ipo.calibration.benchmark import wilson_ci
from ipo.calibration.regime import NiftyRegime
from ipo.calibration.reliability import evaluate_reliability
from ipo.core.config import load_config
from ipo.core.constants import IST
from ipo.core.types import IPOFeatures
from ipo.model.scorer import WeightedScorer

_REPO_ROOT = Path(__file__).resolve().parents[1]
_COST_RATE = 0.005  # ~0.5% round-trip cost approximation for the gross-gain label


def _load(path: Path) -> list[tuple[str, date, float, int]]:
    """Return (name, listing_date, score-inputs-as-features-id, label) rows from skworld."""
    config = load_config(env="dev", environ={})
    scorer = WeightedScorer(config.feature_weights, config.features)
    out: list[tuple[str, date, float, int]] = []
    for fname in ("ipo_listing_gain_train.csv", "ipo_listing_gain_test.csv"):
        fpath = path / fname
        if not fpath.is_file():
            continue
        for row in csv.DictReader(fpath.open(encoding="utf-8", errors="replace")):
            try:
                day = datetime.strptime(row["Date"][:10], "%Y-%m-%d").date()
                qib = float(row["QIB"])
                nii = float(row["HNI"])
                retail = float(row["RII"])
                gain = float(row["Listing Gain"])
            except (KeyError, ValueError):
                continue
            feats = IPOFeatures(
                ipo_id=row["IPO_Name"],
                asof=datetime(day.year, day.month, day.day, 18, tzinfo=IST),
                qib_sub=qib,
                nii_sub=nii,
                retail_sub=retail,
                book_closed=True,
            )
            label = 1 if (gain / 100.0 - _COST_RATE) > 0 else 0
            out.append((row["IPO_Name"], day, scorer.score(feats), label))
    return out


def main() -> None:
    """Run the independent skworld regime replication and write the report."""
    parser = argparse.ArgumentParser(description="Independent regime replication (skworld).")
    parser.add_argument("--path", default="data_store/_kag")
    parser.add_argument("--nifty", default="data/backfill/nifty.csv")
    parser.add_argument("--out", default="docs/REGIME_SKWORLD.md")
    args = parser.parse_args()

    config = load_config(env="dev", environ={})
    cal = config.calibration
    cutoff = config.verdict_thresholds.apply
    regime = NiftyRegime(_REPO_ROOT / args.nifty)

    raw = _load(_REPO_ROOT / args.path)
    if not raw:
        raise SystemExit(f"no skworld CSVs found under {args.path}")
    items = [ScoredItem(n, d, s, lbl) for (n, d, s, lbl) in raw]
    rows = walk_forward(
        items, cal.method, initial=cal.walk_forward_initial, step=cal.walk_forward_step
    )

    def seg(name: str, rs: list[BacktestRow]) -> str:
        if not rs:
            return f"| {name} | 0 | — | — | — | — | — |"
        rep = evaluate_reliability([r.prob for r in rs], [r.label for r in rs], cal.n_buckets)
        applied = [r for r in rs if r.prob >= cutoff]
        pos = sum(r.label for r in applied)
        prec = f"{pos / len(applied):.0%}" if applied else "n/a"
        lo, hi = wilson_ci(pos, len(applied))
        return (
            f"| {name} | {len(rs)} | {rep.base_rate:.0%} | {rep.auc:.2f} | {rep.ece:.3f} | "
            f"{prec} (N={len(applied)}) | [{lo:.0%}, {hi:.0%}] |"
        )

    cold = [r for r in rows if regime.is_cold(r.listing_date)]
    hot = [r for r in rows if not regime.is_cold(r.listing_date)]
    deep = [r for r in rows if 2011 <= r.listing_date.year <= 2013]

    lines = [
        "# Regime Replication — independent skworld Kaggle sample (2010+, cold-richer)",
        "",
        "*Independent check, NOT mixed into the official calibrator (different label: gross "
        "listing gain net of ~0.5% cost). Same subscription-only model + walk-forward + "
        "regime segmentation. Question: does 'cold calibration degrades' replicate on more "
        "cold data? Not financial advice.*",
        "",
        f"OOS IPOs: **{len(rows)}** | cold: **{len(cold)}** | hot: **{len(hot)}** | "
        f"deep-cold 2011–13: **{len(deep)}**",
        "",
        "| Regime | N | Base | AUC | ECE | APPLY prec | 95% CI |",
        "|---|---|---|---|---|---|---|",
        seg("All", rows),
        seg("Hot", hot),
        seg("Cold (neg 3m trend/drawdown)", cold),
        seg("Deep-cold 2011–2013", deep),
        "",
        "## Reading",
        "",
        "Compare the **Cold ECE** here against the official-only result (cold ECE ~0.10–0.14, "
        "over the 0.10 tolerance). If cold ECE is similarly high on this larger, independent, "
        "cold-rich sample, the regime-dependence of the *probability* is a real, replicated "
        "finding — reinforcing the gate/flag decision, not a small-sample fluke. If cold ECE "
        "is fine here, our cold degradation was likely a thin-sample artifact. The *ranking* "
        "(AUC, APPLY vs base) is the apples-to-apples check; the absolute probability differs "
        "because the label definition differs.",
    ]
    (_REPO_ROOT / args.out).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))  # noqa: T201


if __name__ == "__main__":
    main()
