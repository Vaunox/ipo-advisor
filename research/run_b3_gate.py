# =============================================================================================
# QUARANTINED — B3 cheap-adds re-calibration gate (v2). EXCLUDED FROM THE BUILD (research/ is never
# packaged: the engine bundles only src/ipo/ + the PWA). Retained for evidence / possible re-test.
# Do NOT wire any of these features live without re-running the gate and PROMOTING with a fitted
# weight. Evidence + verdicts: docs/B3_GATE.md.
# =============================================================================================
"""B3 cheap feature adds — do NII split / bucketed issue size earn their place?

Same burden of proof as GMP and the enhancement gate (docs/ENHANCEMENT_GATE.md): each feature is
scored **WITH vs WITHOUT** on the same IPOs, walk-forward OOS, the **calibrator refit per arm**
(never a fitted per-feature coefficient — GMP-parity methodology), reporting ECE + AUC and a
paired-bootstrap CI on the AUC lift across ≥3 splits. The arm score is
``base_score + prior_weight * normalized_feature`` computed here, so **no src/ change is needed to
gate** — only if a feature PROMOTES.

Honest clean-coverage (reported before the verdict):
* **NII split (sNII/bNII)** — recovered from the cached ``ipo-active-category`` raws: 235/293.
* **Bucketed issue size** (``total_cr``) — from the Chittorgarh enhancement pull: 293/293.
* **Pricing-vs-band** — NOT gated: backfill cut-off ≡ band top (no clean variation) → data-limited.
* **BRLM reputation** — NOT gated here: needs a point-in-time league table (leakage-prone); assessed
  separately, see docs/B3_GATE.md.

Reuses the enhancement harness (``run_arm`` / ``synthesize`` — refit per arm, bootstrap CI, splits).
"""

from __future__ import annotations

import csv
import glob
import json
from collections.abc import Callable
from pathlib import Path

from run_enhancement_gate import _asof, _eligible, _label, _ReportRow, run_arm, synthesize

from ipo.calibration.backtest import ScoredItem
from ipo.calibration.dataset import load_records_from_csv
from ipo.core.config import AppConfig
from ipo.core.config import load_config as _load_config
from ipo.core.types import IPORecord
from ipo.features.build import build_features
from ipo.features.normalize import saturate
from ipo.model.scorer import WeightedScorer

_ROOT = Path(__file__).resolve().parents[1]

# Prior weights the features enter the linear score at (GMP-parity: fixed, not fitted; the
# calibrator refit per arm is what adapts). Comparable to the existing subscription weights.
_W_SNII = 0.10
_W_BNII = 0.10
_W_SIZE = 0.05
_SIZE_SCALE_CR = 1000.0  # saturation scale for issue size in ₹cr (₹1000cr → ~0.63)


def _symbol_of(ipo_id: str) -> str:
    """backfill ipo_id is ``SYMBOL-YYYY-MM-DD`` — strip the trailing listing date."""
    return ipo_id.rsplit("-", 3)[0]


def _recover_nii_split() -> dict[str, tuple[float, float]]:
    """symbol → (sNII, bNII) multiples, re-parsed from the cached ipo-active-category raws."""

    def value_for(rows: list[dict[str, object]], needle: str) -> float | None:
        for row in rows:
            if needle in str(row.get("category", "")):
                raw = str(row.get("noOfTotalMeant", "")).strip()
                try:
                    return float(raw) if raw else None
                except ValueError:
                    return None
        return None

    out: dict[str, tuple[float, float]] = {}
    for path in glob.glob(str(_ROOT / "data_store" / "raw_cache" / "nse_sub" / "*.json")):
        blob = json.loads(Path(path).read_text(encoding="utf-8"))
        symbol = str(blob["url"]).split("symbol=")[-1]
        try:
            rows = json.loads(blob["content"]).get("dataList", [])
        except (json.JSONDecodeError, AttributeError):
            continue
        snii = value_for(rows, "Two Lakh Rupees upto Ten Lakh")
        bnii = value_for(rows, "more than Ten Lakh Rupees")
        if snii is not None and bnii is not None:
            out[symbol] = (snii, bnii)
    return out


def _recover_issue_size() -> dict[str, float]:
    """ipo_id → total issue size (₹cr) from the enhancement pull (status=ok rows)."""
    out: dict[str, float] = {}
    main = _ROOT / "data_store" / "_enhancement" / "enhancement_main.csv"
    for row in csv.DictReader(main.open(encoding="utf-8")):
        if row.get("status") != "ok":
            continue
        raw = str(row.get("total_cr", "")).strip()
        if raw not in ("", "None", "nan"):
            try:
                out[row["ipo_id"]] = float(raw)
            except ValueError:
                pass
    return out


def _paired(
    records: list[IPORecord],
    scorer: WeightedScorer,
    config: AppConfig,
    add_of: Callable[[IPORecord], float | None],
) -> tuple[list[ScoredItem], list[ScoredItem], float]:
    """Baseline vs arm ScoredItems over the subset where ``add_of`` yields a score delta."""
    base: list[ScoredItem] = []
    arm: list[ScoredItem] = []
    pos = 0
    for rec in _eligible(records):
        add = add_of(rec)
        if add is None:
            continue
        asof = _asof(rec)
        label = _label(rec, config)
        score = scorer.score(build_features(rec, asof, config=config.features))
        base.append(ScoredItem(rec.ipo_id, rec.listing_date, score, label))  # type: ignore[arg-type]
        arm.append(ScoredItem(rec.ipo_id, rec.listing_date, score + add, label))  # type: ignore[arg-type]
        pos += label
    rate = pos / len(base) if base else 0.0
    return base, arm, rate


def main() -> None:
    config = _load_config()
    records = load_records_from_csv(_ROOT / "data" / "backfill" / "mainboard_ipos.csv")
    scorer = WeightedScorer(config.feature_weights, config.features)
    method = config.calibration.method
    cutoff = config.verdict_thresholds.apply
    sub_scale = config.features.subscription.saturation_scale_x

    nii = _recover_nii_split()
    size = _recover_issue_size()

    def split_add(rec: IPORecord) -> float | None:
        sb = nii.get(_symbol_of(rec.ipo_id))
        if sb is None:
            return None
        snii, bnii = sb
        return _W_SNII * saturate(snii, sub_scale) + _W_BNII * saturate(bnii, sub_scale)

    def size_add(rec: IPORecord) -> float | None:
        tc = size.get(rec.ipo_id)
        return None if tc is None else _W_SIZE * saturate(tc, _SIZE_SCALE_CR)

    arms = [
        ("NII split (sNII + bNII)", split_add),
        ("Bucketed issue size", size_add),
    ]
    report: list[_ReportRow] = []
    for name, add_of in arms:
        base, arm, rate = _paired(records, scorer, config, add_of)
        results, prec_wo, prec_w = run_arm(base, arm, method=method, cutoff=cutoff)
        verdict, why = synthesize(name, len(base), results)
        report.append((name, len(base), rate, verdict, why, results, prec_wo, prec_w))
        print(f"\n### {name}: {verdict}  (N={len(base)}, base rate {rate:.0%})")
        for r in results:
            print(
                f"   {r.initial}/{r.step} OOS={r.n_oos} {'keep' if r.keep else 'cut '} "
                f"AUC {r.auc_wo:.3f}->{r.auc_w:.3f} ECE {r.ece_wo:.3f}->{r.ece_w:.3f} "
                f"lift {r.lift:+.3f} [{r.lo:+.3f},{r.hi:+.3f}]"
            )
    _write_report(_ROOT / "docs" / "B3_GATE.md", report, cutoff=cutoff)
    print("\nwrote docs/B3_GATE.md")


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def _write_report(out: Path, report: list[_ReportRow], *, cutoff: float) -> None:
    lines = [
        "# B3 cheap-adds re-calibration gate — NII split / bucketed issue size",
        "",
        "*Each feature scored WITH vs WITHOUT on the same IPOs, walk-forward OOS, "
        "**calibrator refit per arm** (GMP-parity — fixed prior weight, not a fitted "
        "coefficient), ECE + AUC + a paired-bootstrap CI on the AUC lift across ≥3 splits. "
        "The null hypothesis is **QIB-redundancy**; the burden of proof is on the feature. "
        "Data recovered from the cached NSE raws (NII split) and the Chittorgarh pull "
        "(issue size). Engineering/research reference — not financial advice.*",
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
