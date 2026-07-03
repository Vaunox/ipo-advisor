"""Enhancement re-calibration gate — do OFS / valuation / anchor earn their place?

The same burden of proof GMP got (docs/GMP_GATE.md): each feature is scored WITH vs WITHOUT on
the same IPOs, walk-forward out-of-sample, the **calibrator refit per arm** (never bolted onto the
official-only calibrator with prior weights), reporting ECE + AUC and a paired-bootstrap CI on the
AUC lift, across several walk-forward splits (N is modest — trust only what survives all).

Run SEPARATELY per feature so a brittle field (valuation) can't contaminate a clean one (OFS):

* **OFS** — ``ofs_fraction`` from issue structure (clean, ~full coverage).
* **Valuation** — ``relative_valuation = issue_pe / peer_median_pe``, gated ONLY on the hand-QA'd
  **clean-coverage** subset (both a positive post-issue P/E and a clean peer median). If that
  subset is too thin, the valuation gate is reported **INCONCLUSIVE (data-quality-limited)**,
  not a pass/fail (operator directive).
* **Anchor** — ``anchor_quality`` from the anchor book (optional CSV; skipped if absent).

Reads the backfill from ``data_store/_enhancement/`` (Chittorgarh research pull; see
scripts/backfill_enhancement.py). Only the derived report (docs/ENHANCEMENT_GATE.md) is committed.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections.abc import Callable
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
from ipo.features.build import build_features
from ipo.model.scorer import WeightedScorer

_ROOT = Path(__file__).resolve().parents[1]
_STORE = _ROOT / "data_store" / "_enhancement"

# Minimum clean-coverage subset below which a feature's gate is data-quality-limited, not a verdict.
_MIN_CLEAN = 60

# Valuation hand-QA sanity bounds (peer P/E is brittle — Deep Dive #2). A usable P/E *comparator*
# sits in [5, 80]; outside that the "peer" is a bad-earnings-year artifact, not an anchor. The
# issuer's own post-issue P/E must sit in [3, 120] (excludes loss-maker artifacts). The trustworthy
# valuation subset requires >=2 surviving peers AND an in-range issuer P/E — nothing forced.
_PEER_LO, _PEER_HI = 5.0, 80.0
_ISSUE_LO, _ISSUE_HI = 3.0, 120.0


def _f(v: str | None) -> float | None:
    if v is None or str(v).strip() in ("", "None", "nan"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _load_enh() -> dict[str, dict[str, object]]:
    """ipo_id -> per-IPO enhancement fields (ofs / valuation / anchor), keyed for the gate arms."""
    enh: dict[str, dict[str, object]] = {}
    main = _STORE / "enhancement_main.csv"
    for r in csv.DictReader(main.open(encoding="utf-8")):
        if r.get("status") != "ok":
            continue
        enh[r["ipo_id"]] = {
            "ofs_fraction": _f(r.get("ofs_fraction")),
            "issue_pe": _f(r.get("issue_pe")),
            "peer_median_pe": _f(r.get("peer_median_pe")),
            "relative_valuation": _f(r.get("relative_valuation")),
            "val_flag": r.get("val_flag") or "",
        }
    # Hand-QA the brittle peer P/E: recompute a *trustworthy* peer median under the sanity bounds
    # (>=2 surviving peers, issuer post-P/E in range). This is the subset the valuation gate uses.
    peers_path = _STORE / "peer_tables.json"
    peers = json.loads(peers_path.read_text(encoding="utf-8")) if peers_path.is_file() else {}
    for iid, e in enh.items():
        ipe = e["issue_pe"]
        prows = peers.get(iid, {}).get("peer_rows", [])
        surv = [
            p[1] for p in prows if isinstance(p[1], (int, float)) and _PEER_LO <= p[1] <= _PEER_HI
        ]
        ok = isinstance(ipe, float) and _ISSUE_LO <= ipe <= _ISSUE_HI and len(surv) >= 2
        e["val_trustworthy"] = ok
        if ok:
            med = round(statistics.median(surv), 2)
            e["peer_median_strict"] = med
            e["relative_valuation_strict"] = round(ipe / med, 4)  # type: ignore[operator]

    anchor = _STORE / "anchor.csv"  # optional: ipo_id, anchor_quality
    if anchor.is_file():
        for r in csv.DictReader(anchor.open(encoding="utf-8")):
            if r["ipo_id"] in enh:
                enh[r["ipo_id"]]["anchor_quality"] = _f(r.get("anchor_quality"))
    return enh


def _eligible(records: list[IPORecord]) -> list[IPORecord]:
    return [
        r
        for r in records
        if r.segment is Segment.MAINBOARD and r.listing_open is not None and r.qib_sub is not None
    ]


def _asof(rec: IPORecord) -> datetime:
    return datetime(rec.close_date.year, rec.close_date.month, rec.close_date.day, 18, tzinfo=IST)


def _label(rec: IPORecord, config: AppConfig) -> int:
    return int(
        is_positive(
            net_listing_return(
                rec.issue_price,
                rec.listing_open,  # type: ignore[arg-type]
                config.sell_costs,
                nominal_application_value=config.calibration.nominal_application_value,
            )
        )
    )


def _build_arm(
    records: list[IPORecord],
    enh: dict[str, dict[str, object]],
    scorer: WeightedScorer,
    config: AppConfig,
    inject: Callable[[IPORecord, dict[str, object]], dict[str, object] | None],
) -> tuple[list[ScoredItem], list[ScoredItem], float]:
    """Paired (baseline, arm) items over the subset where ``inject`` yields record updates.

    Baseline = the official-only record (enhancement fields ``None``); arm = the same record with
    the feature injected. Both arms are the SAME IPOs with the SAME labels/dates — only the feature
    changes — so the calibrator refit per arm isolates the feature's effect.
    """
    base: list[ScoredItem] = []
    arm: list[ScoredItem] = []
    pos = 0
    for rec in _eligible(records):
        e = enh.get(rec.ipo_id)
        if e is None:
            continue
        upd = inject(rec, e)
        if upd is None:
            continue
        asof = _asof(rec)
        label = _label(rec, config)
        f_base = build_features(rec, asof, config=config.features)
        f_arm = build_features(rec.model_copy(update=upd), asof, config=config.features)
        base.append(ScoredItem(rec.ipo_id, rec.listing_date, scorer.score(f_base), label))  # type: ignore[arg-type]
        arm.append(ScoredItem(rec.ipo_id, rec.listing_date, scorer.score(f_arm), label))  # type: ignore[arg-type]
        pos += label
    rate = pos / len(base) if base else 0.0
    return base, arm, rate


def _bootstrap_lift(
    rows_wo: list[BacktestRow], rows_w: list[BacktestRow], *, seed: int = 17, n: int = 2000
) -> tuple[float, float, float]:
    """Paired-bootstrap CI on AUC(with) − AUC(without) over the shared OOS rows."""
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
    return (sum(r.label for r in applied) / len(applied), len(applied)) if applied else (None, 0)


@dataclass(frozen=True)
class SplitResult:
    """Gate + lift for one walk-forward split."""

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


# One per-feature report row: (name, N, base_rate, verdict, why, splits, prec_without, prec_with).
_ReportRow = tuple[
    str, int, float, str, str, list[SplitResult], tuple[float | None, int], tuple[float | None, int]
]


def _splits_for(n: int) -> list[tuple[int, int]]:
    """A few walk-forward splits scaled to the subset size (trust only what survives all)."""
    return [
        (int(n * 0.60), max(8, int(n * 0.20))),
        (int(n * 0.50), max(6, int(n * 0.15))),
        (int(n * 0.40), max(5, int(n * 0.10))),
    ]


def run_arm(
    base: list[ScoredItem], arm: list[ScoredItem], *, method: str, cutoff: float
) -> tuple[list[SplitResult], tuple[float | None, int], tuple[float | None, int]]:
    """Run every split for one arm; also APPLY-precision (primary split) for both arms."""
    n = len(base)
    results: list[SplitResult] = []
    prec_wo: tuple[float | None, int] = (None, 0)
    prec_w: tuple[float | None, int] = (None, 0)
    for k, (initial, step) in enumerate(_splits_for(n)):
        if n < initial + step or initial < 10:
            continue
        gate = gmp_recalibration_gate(base, arm, method=method, initial=initial, step=step)
        rows_wo = walk_forward(base, method, initial=initial, step=step)
        rows_w = walk_forward(arm, method, initial=initial, step=step)
        lift, lo, hi = _bootstrap_lift(rows_wo, rows_w)
        if k == 0:
            prec_wo = _apply_precision(rows_wo, cutoff)
            prec_w = _apply_precision(rows_w, cutoff)
        results.append(
            SplitResult(
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
            )
        )
    return results, prec_wo, prec_w


def synthesize(
    name: str, n: int, results: list[SplitResult], *, min_clean: int = _MIN_CLEAN
) -> tuple[str, str]:
    """One honest verdict per feature (burden of proof on the feature)."""
    if n < min_clean or not results:
        return (
            "INCONCLUSIVE (data-quality-limited)",
            f"Only {n} clean IPOs — too few to distinguish signal from noise. Not a pass/fail.",
        )
    keeps = sum(r.keep for r in results)
    if any(r.hi < 0 for r in results) or keeps == 0:
        return "CUT", f"{name} does not improve (or degrades) the model on any split — not earned."
    if keeps == len(results) and all(r.lo > 0 for r in results):
        return (
            "EARNED",
            f"{name} improves the model across every split with a lift CI clear of zero.",
        )
    return (
        "NOT EARNED",
        f"No significant lift: the AUC-lift CI includes zero and/or the keep/cut call flips with "
        f"the walk-forward window. On this sample {name} does not demonstrably help — stays out.",
    )


# ---- feature injectors (record fields to set for the arm; None ⇒ IPO outside this arm) ----
def inject_ofs(rec: IPORecord, e: dict[str, object]) -> dict[str, object] | None:
    v = e.get("ofs_fraction")
    return {"ofs_fraction": v} if v is not None else None


def inject_val(rec: IPORecord, e: dict[str, object]) -> dict[str, object] | None:
    if not e.get("val_trustworthy"):  # hand-QA'd subset only (sanity-bounded peer median)
        return None
    return {"issue_pe": e["issue_pe"], "peer_median_pe": e["peer_median_strict"]}


def inject_anchor(rec: IPORecord, e: dict[str, object]) -> dict[str, object] | None:
    return None  # anchor_quality is injected via a prebuilt anchor_book arm (added once scraped)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enhancement re-calibration gate (OFS/valuation/anchor)."
    )
    parser.add_argument("--csv", default="data/backfill/mainboard_ipos.csv")
    parser.add_argument("--out", default="data_store/_enhancement/gate_output.md")
    args = parser.parse_args()

    config = load_config()
    records = load_records_from_csv(_ROOT / args.csv)
    scorer = WeightedScorer(config.feature_weights, config.features)
    enh = _load_enh()
    method = config.calibration.method
    cutoff = config.verdict_thresholds.apply

    arms = [("OFS (ofs_fraction)", inject_ofs), ("Valuation (relative_valuation)", inject_val)]
    if any("anchor_quality" in e for e in enh.values()):
        arms.append(("Anchor (anchor_quality)", inject_anchor))

    report: list[_ReportRow] = []
    for name, inject in arms:
        base, arm, rate = _build_arm(records, enh, scorer, config, inject)
        results, prec_wo, prec_w = run_arm(base, arm, method=method, cutoff=cutoff)
        verdict, why = synthesize(name, len(base), results)
        report.append((name, len(base), rate, verdict, why, results, prec_wo, prec_w))
        print(f"\n### {name}: {verdict}  (N={len(base)}, base rate {rate:.0%})")
        for r in results:
            print(
                f"   split {r.initial}/{r.step} OOS={r.n_oos} {'keep' if r.keep else 'cut '} "
                f"AUC {r.auc_wo:.3f}->{r.auc_w:.3f} ECE {r.ece_wo:.3f}->{r.ece_w:.3f} "
                f"lift {r.lift:+.3f} [{r.lo:+.3f},{r.hi:+.3f}]"
            )

    _write_report(_ROOT / args.out, report, cutoff=cutoff)
    print(f"\nwrote {args.out}")


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def _write_report(out: Path, report: list[_ReportRow], *, cutoff: float) -> None:
    lines = [
        "# Enhancement Re-calibration Gate — OFS / Valuation / Anchor",
        "",
        "*The same burden of proof GMP got: each feature scored WITH vs WITHOUT on the same IPOs, "
        "walk-forward OOS, calibrator refit per arm, ECE + AUC + a bootstrap CI on the lift, "
        "across splits. Gated **separately** so a brittle field can't contaminate a clean one. "
        "Backfill is a Chittorgarh research pull (not a sanctioned ongoing source). "
        "Engineering/research reference — not financial advice.*",
        "",
    ]
    for name, n, rate, verdict, why, results, prec_wo, prec_w in report:
        lines += [
            f"## {name} — **{verdict}**",
            "",
            f"> {why}",
            "",
            f"- Clean-coverage N: **{n}** · base rate {rate:.0%} · APPLY precision @ {cutoff:.2f}: "
            f"off {_pct(prec_wo[0])} (N={prec_wo[1]}) vs on {_pct(prec_w[0])} (N={prec_w[1]})",
            "",
            "| split (initial/step) | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |",
            "|---|---|---|---|---|---|",
        ]
        for r in results:
            lines.append(
                f"| {r.initial}/{r.step} | {r.n_oos} | {'keep' if r.keep else 'cut'} | "
                f"{r.auc_wo:.3f}→{r.auc_w:.3f} | {r.ece_wo:.3f}→{r.ece_w:.3f} | "
                f"{r.lift:+.3f} [{r.lo:+.3f}, {r.hi:+.3f}] |"
            )
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
