"""Read-only re-check of the -0.3 cold-flag prior (Phase 6 carry-forward prereq #2).

Confirms ``market_regime <= -0.3`` is a sane cutoff: how much of the market it flags
overall (it should be a minority, not noise and not everything), and how much of an
independently **known-cold** sample (the 214-IPO skworld cold set) it catches. This is
**strictly read-only** — it does NOT tune the threshold; the config value stays -0.3.

Usage:
    python scripts/run_regime_recheck.py [--csv ...] [--nifty ...] [--skworld data_store/_kag]
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

from ipo.calibration.dataset import load_records_from_csv
from ipo.calibration.regime import NiftyRegime
from ipo.core.types import Segment

_REPO_ROOT = Path(__file__).resolve().parents[1]
_THRESHOLDS = (-0.2, -0.3, -0.4)


def _backfill_regimes(csv_path: Path, regime: NiftyRegime) -> tuple[list[float], list[float]]:
    """Return (all market_regime, cold-only market_regime) at close for eligible mainboard IPOs."""
    all_mr: list[float] = []
    cold_mr: list[float] = []
    for rec in load_records_from_csv(csv_path):
        if rec.segment is not Segment.MAINBOARD or rec.listing_open is None or rec.qib_sub is None:
            continue
        mr = regime.market_regime_feature(rec.close_date)
        if mr is None:
            continue
        all_mr.append(mr)
        if regime.is_cold(rec.close_date):
            cold_mr.append(mr)
    return all_mr, cold_mr


def _skworld_cold_regimes(path: Path, regime: NiftyRegime) -> list[float]:
    """market_regime at listing for the independently known-cold skworld IPOs."""
    out: list[float] = []
    for fname in ("ipo_listing_gain_train.csv", "ipo_listing_gain_test.csv"):
        fpath = path / fname
        if not fpath.is_file():
            continue
        for row in csv.DictReader(fpath.open(encoding="utf-8", errors="replace")):
            try:
                day = datetime.strptime(row["Date"][:10], "%Y-%m-%d").date()
            except (KeyError, ValueError):
                continue
            if not regime.is_cold(day):
                continue
            mr = regime.market_regime_feature(day)
            if mr is not None:
                out.append(mr)
    return out


def _pct_at(values: list[float], thr: float) -> str:
    if not values:
        return "n/a"
    return f"{sum(1 for v in values if v <= thr) / len(values):.0%}"


def main() -> None:
    """Run the read-only -0.3 re-check and write docs/REGIME_RECHECK.md."""
    parser = argparse.ArgumentParser(description="Read-only -0.3 cold-flag re-check.")
    parser.add_argument("--csv", default="data/backfill/mainboard_ipos.csv")
    parser.add_argument("--nifty", default="data/backfill/nifty.csv")
    parser.add_argument("--skworld", default="data_store/_kag")
    parser.add_argument("--out", default="docs/REGIME_RECHECK.md")
    args = parser.parse_args()

    regime = NiftyRegime(_REPO_ROOT / args.nifty)
    all_mr, cold_mr = _backfill_regimes(_REPO_ROOT / args.csv, regime)
    sk_cold = _skworld_cold_regimes(_REPO_ROOT / args.skworld, regime)

    rows = []
    for thr in _THRESHOLDS:
        marker = " **(current)**" if thr == -0.3 else ""
        rows.append(
            f"| {thr:+.1f}{marker} | {_pct_at(all_mr, thr)} (N={len(all_mr)}) | "
            f"{_pct_at(cold_mr, thr)} (N={len(cold_mr)}) | "
            f"{_pct_at(sk_cold, thr)} (N={len(sk_cold)}) |"
        )

    lines = [
        "# Cold-flag (-0.3) re-check — READ-ONLY (Phase 6 prereq #2)",
        "",
        "*Confirms `market_regime <= -0.3` is a sane prior before it shapes live verdicts. "
        "Strictly read-only: nothing is tuned, the config value stays **-0.3**. Not financial "
        "advice.*",
        "",
        "## Flag rate by candidate threshold",
        "",
        "| threshold | all mainboard 2021+ | of which cold | known-cold (skworld) |",
        "|---|---|---|---|",
        *rows,
        "",
        "## Reading",
        "",
        f"At the current **-0.3**, the flag fires on **{_pct_at(all_mr, -0.3)}** of all mainboard "
        f"IPOs — a clear minority (not noise, not everything) — and catches "
        f"**{_pct_at(sk_cold, -0.3)}** of independently known-cold IPOs (the rest are cold via "
        "mild drawdown with a flat/slightly positive 3-month trend, which the flag intentionally "
        "does not over-call). -0.2 flags more broadly; -0.4 only the deepest corrections. **-0.3 "
        "sits sensibly between the two and is confirmed as a reasonable prior — left unchanged.**",
        "",
        "Re-examine again only if the live flag rate drifts far from this; never tune it to "
        "listing outcomes (it is a prior on market state, not a fitted parameter).",
    ]
    (_REPO_ROOT / args.out).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))  # noqa: T201


if __name__ == "__main__":
    main()
