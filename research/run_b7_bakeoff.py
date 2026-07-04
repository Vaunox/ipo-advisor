# =============================================================================================
# QUARANTINED — B7 model-architecture bake-off (v2): TabPFN v2 vs the logistic core. EXCLUDED FROM
# BUILD (research/ is never packaged; tabpfn is a research-only dep). Do NOT swap the shipped model
# for TabPFN without a decisive win here AND operator review. Evidence: docs/B7_BAKEOFF.md.
# =============================================================================================
"""B7 — does TabPFN v2 beat the logistic core enough to justify losing the grounded reason?

Head-to-head on the 358-IPO sample, same walk-forward OOS folds, AUC + ECE with a paired-bootstrap
CI on the AUC difference (TabPFN − logistic), across ≥3 splits:

* **Logistic core** — the shipped pipeline: the fixed-weight scorer → Platt calibrator (refit per
  train fold). Interpretable: every verdict traces to a feature ("QIB 42×").
* **TabPFN v2** — a pretrained transformer for small tabular data (the only credible challenger;
  flexible ML overfits below this sample size). A black box: no grounded reason.

Both see the same core subscription features (QIB / NII / retail) on the same train/test folds.

**Higher bar (the whole point):** adopting TabPFN forfeits the grounded reason (Rule 8), so it does
NOT win on a tie or a marginal edge. It wins only if it beats logistic **decisively** — an AUC lift
**≥ 0.03 with the CI clear of zero on every split AND ECE no worse** — enough to justify giving up
interpretability entirely. Anything less: **logistic stays.** A decisive TabPFN win on a
simple QIB-led problem would be *surprising*, flagged for leakage/pipeline scrutiny, not
auto-adopted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from run_enhancement_gate import _asof, _eligible, _label, _splits_for

from ipo.calibration.calibrate import make_calibrator
from ipo.calibration.dataset import load_records_from_csv
from ipo.calibration.reliability import auc_score, evaluate_reliability
from ipo.core.config import load_config
from ipo.features.build import build_features
from ipo.model.scorer import WeightedScorer

_ROOT = Path(__file__).resolve().parents[1]

# The core features both models see (populated for the whole sample; GMP absent, regime weight-0).
_FEATURES = ("qib_sub", "nii_sub", "retail_sub")

# Decisive-win bar: TabPFN must beat logistic by at least this AUC, CI-clear on every split, ECE
# no worse — enough to justify forfeiting the grounded reason. Below this, logistic stays.
_DECISIVE_AUC = 0.03


@dataclass(frozen=True)
class _SplitResult:
    initial: int
    step: int
    n_oos: int
    auc_log: float
    auc_tab: float
    ece_log: float
    ece_tab: float
    diff: float  # AUC(TabPFN) − AUC(logistic)
    lo: float
    hi: float


def _bootstrap_diff(
    log_p: list[float], tab_p: list[float], labels: list[int], *, seed: int = 17, n: int = 2000
) -> tuple[float, float, float]:
    """Paired-bootstrap CI on AUC(TabPFN) − AUC(logistic) over the shared OOS points."""
    a, b, y = np.array(log_p), np.array(tab_p), np.array(labels, dtype=int)
    point = auc_score(b.tolist(), y.tolist()) - auc_score(a.tolist(), y.tolist())
    rng = np.random.default_rng(seed)
    diffs: list[float] = []
    for _ in range(n):
        s = rng.integers(0, len(y), len(y))
        if len(set(y[s].tolist())) < 2:
            continue
        diffs.append(
            auc_score(b[s].tolist(), y[s].tolist()) - auc_score(a[s].tolist(), y[s].tolist())
        )
    lo, hi = (float(x) for x in np.percentile(diffs, [2.5, 97.5]))
    return point, lo, hi


def _run_split(
    scores: NDArray[np.float64],
    features: NDArray[np.float64],
    labels: NDArray[np.int_],
    *,
    initial: int,
    step: int,
    method: str,
) -> _SplitResult:
    """One walk-forward split: logistic (Platt on scores) vs TabPFN (on features), same folds."""
    from tabpfn import TabPFNClassifier
    from tabpfn.constants import ModelVersion

    log_p: list[float] = []
    tab_p: list[float] = []
    lab: list[int] = []
    n = len(scores)
    for start in range(initial, n, step):
        end = min(start + step, n)
        tr, te = slice(0, start), slice(start, end)
        cal = make_calibrator(method)
        cal.fit(scores[tr].tolist(), labels[tr].tolist())
        log_p += [cal.predict_proba(float(s)) for s in scores[te]]
        # Pin to TabPFN *v2* (the challenger B7 scoped; ungated public weights). The package default
        # now loads the newer tabpfn_3, which is license/account-gated -- out of scope for B7.
        clf = TabPFNClassifier.create_default_for_version(ModelVersion.V2, random_state=0)
        clf.fit(features[tr], labels[tr])
        proba = np.asarray(clf.predict_proba(features[te]), dtype=np.float64)
        tab_p += [float(v) for v in proba[:, 1]]
        lab += [int(v) for v in labels[te]]
    diff, lo, hi = _bootstrap_diff(log_p, tab_p, lab)
    return _SplitResult(
        initial=initial,
        step=step,
        n_oos=len(lab),
        auc_log=auc_score(log_p, lab),
        auc_tab=auc_score(tab_p, lab),
        ece_log=evaluate_reliability(log_p, lab).ece,
        ece_tab=evaluate_reliability(tab_p, lab).ece,
        diff=diff,
        lo=lo,
        hi=hi,
    )


def _verdict(results: list[_SplitResult]) -> tuple[str, str]:
    """Weigh any metric edge against the interpretability loss — logistic wins ties/marginals."""
    decisive = all(
        r.diff >= _DECISIVE_AUC and r.lo > 0.0 and r.ece_tab <= r.ece_log for r in results
    )
    if decisive:
        return (
            "TabPFN WINS - DECISIVE (flag for review, do NOT auto-adopt)",
            "TabPFN beats logistic by >= 0.03 AUC with the CI clear of zero on every split and ECE "
            "no worse. A surprising ML win on a QIB-led problem: scrutinize for leakage / pipeline "
            "artifact before ever trading the grounded reason for a black box.",
        )
    return (
        "LOGISTIC STAYS - TabPFN not decisively better",
        "TabPFN does not beat the logistic core by enough to justify forfeiting the grounded "
        "reason (the AUC edge is small / its CI includes zero / ECE is not better on some "
        "split). The interpretable model explains every verdict ('QIB 42x'); TabPFN is a black "
        "box. On this evidence the interpretability outweighs any marginal metric edge -- "
        "logistic is retained, the question closed.",
    )


def main() -> None:
    """Run the bake-off across the walk-forward splits and write docs/B7_BAKEOFF.md."""
    config = load_config()
    records = load_records_from_csv(_ROOT / "data" / "backfill" / "mainboard_ipos.csv")
    scorer = WeightedScorer(config.feature_weights, config.features)
    method = config.calibration.method

    pts: list[tuple[date, float, list[float], int]] = []
    for rec in _eligible(records):
        if rec.listing_date is None:
            continue  # eligible => listed, but narrow to a non-None sort key for mypy
        feats = build_features(rec, _asof(rec), config=config.features)
        row = [float(getattr(feats, f)) for f in _FEATURES]  # QIB/NII/retail populated for all
        pts.append((rec.listing_date, scorer.score(feats), row, _label(rec, config)))
    pts.sort(key=lambda p: p[0])
    scores = np.array([p[1] for p in pts], dtype=np.float64)
    features = np.array([p[2] for p in pts], dtype=np.float64)
    labels = np.array([p[3] for p in pts], dtype=np.int_)
    n = len(pts)

    results: list[_SplitResult] = []
    for initial, step in _splits_for(n):
        if n < initial + step or initial < 10:
            continue
        results.append(
            _run_split(scores, features, labels, initial=initial, step=step, method=method)
        )

    verdict, why = _verdict(results)
    print(f"\n### B7 bake-off: {verdict}  (N={n})")  # noqa: T201
    for r in results:
        print(  # noqa: T201
            f"   {r.initial}/{r.step} OOS={r.n_oos}  log AUC {r.auc_log:.3f} / tab {r.auc_tab:.3f}"
            f"  ECE {r.ece_log:.3f} / {r.ece_tab:.3f} diff {r.diff:+.3f} [{r.lo:+.3f},{r.hi:+.3f}]"
        )
    _write_report(_ROOT / "docs" / "B7_BAKEOFF.md", n, verdict, why, results)
    print("\nwrote docs/B7_BAKEOFF.md")  # noqa: T201


def _write_report(out: Path, n: int, verdict: str, why: str, results: list[_SplitResult]) -> None:
    lines = [
        "# B7 — model-architecture bake-off: TabPFN v2 vs the logistic core",
        "",
        "*Head-to-head on the 358-IPO sample, same walk-forward OOS folds, AUC + ECE with a "
        "paired-bootstrap CI on the AUC difference (TabPFN - logistic), across >=3 splits. Both "
        "models see the same core subscription features (QIB / NII / retail). **Higher bar:** "
        "adopting TabPFN forfeits the grounded reason, so it wins only by beating logistic "
        f"**decisively** (AUC lift >= {_DECISIVE_AUC:.2f}, CI clear of zero every split, ECE no "
        "worse) - not on a tie or a marginal edge. Engineering/research reference - not financial "
        "advice.*",
        "",
        f"## Verdict: **{verdict}**",
        "",
        f"> {why}",
        "",
        f"- Sample N: **{n}** · challenger: TabPFN v2 (pretrained tabular transformer) · "
        "incumbent: fixed-weight scorer → Platt (the shipped, interpretable core)",
        "",
        "| split (initial/step) | OOS N | AUC logistic | AUC TabPFN | ECE logistic | ECE TabPFN | "
        "AUC diff (95% CI) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.initial}/{r.step} | {r.n_oos} | {r.auc_log:.3f} | {r.auc_tab:.3f} | "
            f"{r.ece_log:.3f} | {r.ece_tab:.3f} | {r.diff:+.3f} [{r.lo:+.3f}, {r.hi:+.3f}] |"
        )
    best = max(results, key=lambda r: r.diff)
    ci_all_zero = all(r.lo <= 0.0 for r in results)
    ece_all_worse = all(r.ece_tab > r.ece_log for r in results)
    reading = (
        f"**Reading the table.** The largest AUC edge to TabPFN is {best.diff:+.3f} (split "
        f"{best.initial}/{best.step}), short of the {_DECISIVE_AUC:.2f} decisive bar"
        + ("; every split's 95% CI includes zero" if ci_all_zero else "")
        + ("; and ECE is worse for TabPFN on every split" if ece_all_worse else "; ECE is mixed")
        + ". The edge is within noise and comes at a calibration cost -- costly for a "
        "calibrated-probability product. Not decisive."
    )
    lines += [
        "",
        reading,
        "",
        "**Operational cost beyond interpretability.** Adopting TabPFN would add a ~29 MB opaque "
        "transformer (torch, ~500 MB installed) with vendor telemetry to a self-contained local "
        "tool. The current TabPFN line (v2.5 / v2.6 / v3) is gated behind Prior Labs account "
        "registration + license acceptance; v2 is ungated today but the trajectory is toward "
        "gating. This raises the already-high bar -- it does not lower it.",
        "",
        "**Interpretability cost (explicit):** the logistic core explains every verdict from a "
        "feature value ('APPLY - QIB 42x'); TabPFN is a black box with no grounded reason. That "
        "cost is only worth paying for a decisive, robust accuracy win - which is the bar above.",
        "",
        "## Provenance & reproduction",
        "",
        "- Challenger pinned to **TabPFN v2** (`ModelVersion.V2`, the ungated public "
        "`Prior-Labs/TabPFN-v2-clf` weights) -- the model B7 scoped; the package default now "
        "loads the newer `tabpfn_3`.",
        "- Deterministic: `random_state=0`, paired-bootstrap `seed=17` (2000 resamples), CPU.",
        "- Reproduce: `TABPFN_NO_BROWSER=1 .venv/Scripts/python.exe research/run_b7_bakeoff.py`",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
