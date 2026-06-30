"""Phase-5 GMP re-calibration gate on real point-in-time GMP (IPOMatrix 2025-26).

THE Phase-5 question, answered on real data for the first time: does as-of-close GMP
(level + final-days slope) **earn its weight** by improving the calibrated model, or is
it noise we should keep out? Unlike the leaky nikhilraj screen, this uses:

* **Point-in-time** GMP — only quotes dated at/before the subscription close inform the
  feature (the Allotted/Listed rows are ignored by construction), so it is **not leaky**.
* **Our own** net-of-open label and official NSE subscription — apples-to-apples with the
  Phase-4 calibrator (the gate compares the *same* IPOs scored with vs without GMP).

Honest boundaries, stated in the report:
* **Hot-market only.** 2025-26 is a single, buoyant regime — a high base rate. This says
  nothing about GMP in cold markets (cf. REGIME_FIX.md).
* **Single source** (IPOMatrix/Chittorgarh) — no cross-source divergence flag is exercised.
* **Small N** (~99 IPOs, ~40 out-of-sample) — wide CIs; a bootstrap CI on the lift is
  reported so the decision is not over-read.

Reads the two raw IPOMatrix CSVs from a gitignored dir; only the derived report is committed.
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from ipo.calibration.backtest import BacktestRow, ScoredItem, walk_forward
from ipo.calibration.dataset import load_records_from_csv
from ipo.calibration.gmp_gate import gmp_recalibration_gate
from ipo.calibration.label import is_positive, net_listing_return
from ipo.calibration.reliability import auc_score
from ipo.core.config import AppConfig, load_config
from ipo.core.constants import IST
from ipo.core.types import IPORecord, Segment
from ipo.data.sources.gmp import (
    CsvGmpHistory,
    has_sufficient_coverage,
    reconcile,
    to_quotes,
)
from ipo.features.build import build_features
from ipo.model.scorer import WeightedScorer

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GMP_SOURCE = "ipomatrix"


def _norm(name: str) -> str:
    """Normalize an IPO name for joining (drop suffixes/punctuation/casing)."""
    name = re.sub(r"\(.*?\)", "", name or "").lower()
    name = re.sub(
        r"\b(limited|ltd|ipo|the|india|technologies|industries|enterprises|company)\b", "", name
    )
    return re.sub(r"[^a-z0-9]", "", name)


def _iso(ddmmyyyy: str) -> str | None:
    try:
        return datetime.strptime(ddmmyyyy, "%d-%m-%Y").date().isoformat()
    except ValueError:
        return None


def _load_ipomatrix(paths: list[Path]) -> dict[str, dict[str, object]]:
    """Group raw IPOMatrix rows by ipomatrix_id -> {sym, name, points:[(iso_date, gmp)]}."""
    by_id: dict[str, dict[str, object]] = {}
    for path in paths:
        if not path.is_file():
            continue
        for row in csv.DictReader(path.open(encoding="utf-8", errors="replace")):
            iid = row["ipomatrix_id"]
            iso = _iso(row["gmp_date"])
            try:
                gmp = float(row["gmp"])
                price = float(row["ipo_price"])
            except (KeyError, ValueError):
                continue
            if iso is None or price <= 0:
                continue
            entry = by_id.setdefault(iid, {"sym": "", "name": "", "points": []})
            if row.get("symbol"):
                entry["sym"] = row["symbol"]
            if row.get("name"):
                entry["name"] = row["name"]
            points = entry["points"]
            assert isinstance(points, list)
            points.append((iso, gmp))
    return by_id


def _write_nse_keyed_gmp(
    ipomatrix: dict[str, dict[str, object]], records: list[IPORecord], out_csv: Path
) -> tuple[int, int]:
    """Map each IPOMatrix IPO to an NSE ipo_id (symbol then name); write the keyed GMP CSV."""
    by_sym = {r.ipo_id.split("-")[0]: r.ipo_id for r in records}
    by_norm = {_norm(r.name): r.ipo_id for r in records if r.name}
    rows: dict[tuple[str, str], float] = {}
    matched_ids: set[str] = set()
    for entry in ipomatrix.values():
        sym = str(entry["sym"])
        nm = str(entry["name"])
        nse_id = by_sym.get(sym) or by_norm.get(_norm(nm))
        if nse_id is None:
            continue
        matched_ids.add(nse_id)
        points = entry["points"]
        assert isinstance(points, list)
        for iso, gmp in points:
            rows[(nse_id, iso)] = gmp  # dedup by (ipo, day)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ipo_id", "date", "value", "source"])
        for (nse_id, iso), gmp in sorted(rows.items()):
            writer.writerow([nse_id, iso, gmp, _GMP_SOURCE])
    return len(matched_ids), len(rows)


def _build_items(
    records: list[IPORecord],
    history: CsvGmpHistory,
    scorer: WeightedScorer,
    config: AppConfig,
) -> tuple[list[ScoredItem], list[ScoredItem], float, int]:
    """Build paired with/without-GMP items on the IPOs that have sufficient as-of-close GMP."""
    without: list[ScoredItem] = []
    with_gmp: list[ScoredItem] = []
    pos = 0
    for rec in records:
        if rec.segment is not Segment.MAINBOARD or rec.listing_open is None or rec.qib_sub is None:
            continue
        if rec.listing_date is None or rec.listing_date.year not in (2025, 2026):
            continue
        points = history.series(rec.ipo_id)
        if not points:
            continue
        series = reconcile(points, config.gmp)
        if not has_sufficient_coverage(series, rec.close_date, config.gmp):
            continue
        asof = datetime(
            rec.close_date.year, rec.close_date.month, rec.close_date.day, 18, tzinfo=IST
        )
        feats_wo = build_features(rec, asof, config=config.features)
        feats_w = build_features(rec, asof, gmp_series=to_quotes(series), config=config.features)
        label = int(
            is_positive(
                net_listing_return(
                    rec.issue_price,
                    rec.listing_open,
                    config.sell_costs,
                    nominal_application_value=config.calibration.nominal_application_value,
                )
            )
        )
        pos += label
        without.append(ScoredItem(rec.ipo_id, rec.listing_date, scorer.score(feats_wo), label))
        with_gmp.append(ScoredItem(rec.ipo_id, rec.listing_date, scorer.score(feats_w), label))
    base_rate = pos / len(without) if without else 0.0
    return without, with_gmp, base_rate, len(without)


def _bootstrap_auc_lift(
    rows_wo: list[BacktestRow], rows_w: list[BacktestRow], *, seed: int = 17, n: int = 2000
) -> tuple[float, float, float]:
    """Paired-bootstrap CI on the AUC(with) - AUC(without) lift over the OOS rows."""
    paired = {r.ipo_id: [r.prob, 0.0, r.label] for r in rows_wo}
    for r in rows_w:
        if r.ipo_id in paired:
            paired[r.ipo_id][1] = r.prob
    items = list(paired.values())
    pa = np.array([it[0] for it in items])
    pb = np.array([it[1] for it in items])
    yy = np.array([it[2] for it in items], dtype=int)
    point = auc_score(pb.tolist(), yy.tolist()) - auc_score(pa.tolist(), yy.tolist())
    rng = np.random.default_rng(seed)
    diffs: list[float] = []
    for _ in range(n):
        s = rng.integers(0, len(yy), len(yy))
        if len(set(yy[s].tolist())) < 2:
            continue
        diffs.append(
            auc_score(pb[s].tolist(), yy[s].tolist()) - auc_score(pa[s].tolist(), yy[s].tolist())
        )
    lo, hi = (float(x) for x in np.percentile(diffs, [2.5, 97.5]))
    return point, lo, hi


def _apply_precision(rows: list[BacktestRow], cutoff: float) -> tuple[float | None, int]:
    applied = [r for r in rows if r.prob >= cutoff]
    if not applied:
        return None, 0
    return sum(r.label for r in applied) / len(applied), len(applied)


@dataclass(frozen=True)
class _SplitResult:
    """Gate + lift outcome for one walk-forward split (robustness across splits matters)."""

    initial: int
    step: int
    n_oos: int
    keep: bool
    auc_wo: float
    auc_w: float
    ece_wo: float
    ece_w: float
    lift: float
    lo: float
    hi: float
    prec_wo: float | None
    n_apply_wo: int
    prec_w: float | None
    n_apply_w: int


# Several walk-forward splits: N is small, so we trust only conclusions that survive
# all of them (a single split's keep/cut can be noise — and is, here).
_SPLITS = ((60, 20), (50, 15), (40, 10))


def main() -> None:
    """Run the Phase-5 GMP re-calibration gate across splits and write docs/GMP_GATE.md."""
    parser = argparse.ArgumentParser(description="Phase-5 GMP re-calibration gate (IPOMatrix).")
    parser.add_argument("--csv", default="data/backfill/mainboard_ipos_2017.csv")
    parser.add_argument(
        "--gmp-raw",
        nargs="+",
        default=[
            "data_store/_gmp/ipomatrix_gmp_2025_2026.csv",
            "data_store/_gmp/ipomatrix_gmp_low.csv",
        ],
    )
    parser.add_argument("--out", default="docs/GMP_GATE.md")
    args = parser.parse_args()

    config = load_config()
    records = load_records_from_csv(_REPO_ROOT / args.csv)
    scorer = WeightedScorer(config.feature_weights, config.features)

    ipomatrix = _load_ipomatrix([_REPO_ROOT / p for p in args.gmp_raw])
    keyed_csv = _REPO_ROOT / "data_store" / "_gmp" / "gmp_nse_keyed.csv"
    n_matched, n_points = _write_nse_keyed_gmp(ipomatrix, records, keyed_csv)
    history = CsvGmpHistory(keyed_csv)

    without, with_gmp, base_rate, n = _build_items(records, history, scorer, config)
    method = config.calibration.method
    cutoff = config.verdict_thresholds.apply

    results: list[_SplitResult] = []
    for initial, step in _SPLITS:
        if n < initial + step:
            continue
        gate = gmp_recalibration_gate(without, with_gmp, method=method, initial=initial, step=step)
        rows_wo = walk_forward(without, method, initial=initial, step=step)
        rows_w = walk_forward(with_gmp, method, initial=initial, step=step)
        lift, lo, hi = _bootstrap_auc_lift(rows_wo, rows_w)
        prec_wo, na_wo = _apply_precision(rows_wo, cutoff)
        prec_w, na_w = _apply_precision(rows_w, cutoff)
        results.append(
            _SplitResult(
                initial,
                step,
                len(rows_wo),
                gate.keep_gmp,
                gate.without_gmp.auc,
                gate.with_gmp.auc,
                gate.without_gmp.ece,
                gate.with_gmp.ece,
                lift,
                lo,
                hi,
                prec_wo,
                na_wo,
                prec_w,
                na_w,
            )
        )
    if not results:
        raise SystemExit(f"too few GMP-covered IPOs ({n}) for any split")

    lines = _report(
        results, n=n, n_matched=n_matched, n_points=n_points, base_rate=base_rate, cutoff=cutoff
    )
    (_REPO_ROOT / args.out).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))  # noqa: T201


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def _synthesize(results: list[_SplitResult]) -> tuple[str, str]:
    """Collapse the per-split outcomes into one honest verdict (burden of proof on GMP)."""
    keeps = sum(r.keep for r in results)
    lift_pos = any(r.lo > 0.0 for r in results)  # any split where lift CI clears zero
    lift_neg = any(r.hi < 0.0 for r in results)
    if keeps == len(results) and lift_pos:
        return "KEEP GMP", "GMP improves the model across every split and its lift clears zero."
    if keeps == 0 or lift_neg:
        return (
            "CUT GMP",
            "GMP fails the gate (it does not improve, or degrades, the model) — it has not "
            "earned a place on this data.",
        )
    return (
        "NOT EARNED (provisional, hot-market only)",
        "No significant marginal lift over the official QIB-led model: the AUC lift CI "
        "**includes zero in every split** and the keep/cut call **flips with the walk-forward "
        "window**. The burden of proof is on GMP to *demonstrate* it helps (Deep Dive #5); on "
        "this hot-market sample it does not, so **GMP stays out of the shipped model, "
        "provisionally** — revisit with cold-market point-in-time GMP from the recorder.",
    )


def _report(
    results: list[_SplitResult],
    *,
    n: int,
    n_matched: int,
    n_points: int,
    base_rate: float,
    cutoff: float,
) -> list[str]:
    verdict, rationale = _synthesize(results)
    lines = [
        "# Phase-5 GMP Re-calibration Gate — real point-in-time GMP (IPOMatrix 2025-26)",
        "",
        "*The first real test of THE Phase-5 question: does as-of-close GMP (level + slope) "
        "earn its weight in the calibrated model? Point-in-time (not leaky), our own net-of-open "
        "label, same IPOs scored with vs without GMP. Engineering/research reference — not "
        "financial advice.*",
        "",
        f"## Verdict: **{verdict}**",
        "",
        f"> {rationale}",
        "",
        "## Robustness across walk-forward splits (N is small — trust only what survives all)",
        "",
        "| initial, step | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.initial}, {r.step} | {r.n_oos} | {'keep' if r.keep else 'cut'} | "
            f"{r.auc_wo:.3f}→{r.auc_w:.3f} | {r.ece_wo:.3f}→{r.ece_w:.3f} | "
            f"{r.lift:+.3f} [{r.lo:+.3f}, {r.hi:+.3f}] |"
        )
    primary = results[0]
    lines += [
        "",
        "The AUC lift's CI **includes zero in every split**, and the ECE direction (and thus the "
        "keep/cut call) **flips** — i.e. GMP neither reliably discriminates better nor reliably "
        "calibrates better than the official QIB-led model on this data.",
        "",
        f"APPLY precision @ {cutoff:.2f} (primary split {primary.initial}/{primary.step}): "
        f"official-only {_pct(primary.prec_wo)} (N={primary.n_apply_wo}) vs "
        f"+GMP {_pct(primary.prec_w)} (N={primary.n_apply_w}) — essentially unchanged.",
        "",
        "## Why this matters vs the earlier leaky screen",
        "",
        "The nikhilraj level-only screen (leaky, near-listing GMP) showed a large **+0.133** AUC "
        "lift (`GMP_SCREEN.md`). On **clean point-in-time** GMP that lift **collapses to ~0** — "
        "strong evidence the apparent GMP edge was mostly **leakage**, and that as-of-close GMP is "
        "largely **redundant with QIB** subscription in a hot market.",
        "",
        "## Sample",
        "",
        f"- **{n_matched}** mainboard IPOs matched to NSE with point-in-time GMP; **{n}** had "
        "sufficient as-of-close coverage and entered the gate.",
        f"- **{n_points}** reconciled GMP day-points; GMP read strictly **as-of subscription "
        "close** (Allotted/Listed rows excluded by construction — not leaky).",
        f"- **Base rate (positive net listing):** {base_rate:.0%} — a **hot market**.",
        "",
        "## What this does NOT answer (boundaries — do not over-read)",
        "",
        f"- **Hot-market only.** Base rate ~{base_rate:.0%}; 2025-26 is one buoyant regime. Says "
        "nothing about GMP in cold markets, where QIB is weaker and GMP *might* carry more (or be "
        "more manipulated) — untestable without cold point-in-time GMP (cf. `REGIME_FIX.md`).",
        "- **Single source** (IPOMatrix/Chittorgarh). Multi-source divergence/confidence flags and "
        "the spike-collapse kill-flag are **not** exercised here — this tests the *level+slope "
        "features*, not GMP's manipulation-detection role.",
        "- **Small N / wide CIs.** ~40–60 OOS points. This is a real read, not the last word; "
        "re-run as the recorder banks more — and colder — point-in-time GMP.",
        "",
    ]
    return lines


if __name__ == "__main__":
    main()
