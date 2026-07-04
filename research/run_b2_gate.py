# =============================================================================================
# QUARANTINED — B2 second-half gate (v2): does India VIX earn a WEIGHT in the score? EXCLUDED FROM
# BUILD (research/ is never packaged). The B2 flag-enrichment half already shipped at weight 0; this
# tests the *score-feature* half. Do NOT wire a VIX weight live without a PROMOTE here.
# Evidence + verdict: docs/B2_SCORE_GATE.md.
# =============================================================================================
"""B2 second half — does India VIX earn a weight in the score, beyond the cold-market flag?

The B2 flag-enrichment half (VIX into the cold flag at weight 0) already shipped. This gates the
*score-feature* half: India VIX entered as a weighted input, same burden of proof as B3/GMP —
scored **WITH vs WITHOUT** on the same IPOs, walk-forward OOS, the **calibrator refit per arm**
(GMP-parity: a fixed prior weight, never a fitted coefficient), ECE + AUC + a paired-bootstrap CI
on the AUC lift across ≥3 splits. Arm score = ``base_score + prior_weight * feature`` computed
here, so **no src/ change is needed to gate** — only if it PROMOTES.

Honest prior (the blueprint's own): **QIB-redundant.** In a fearful (high-VIX) tape, QIB bids
cautiously, so the VIX signal likely already echoes through the QIB subscription the model reads.
The a-priori sign is "high VIX → risk-off → weaker listing → lower score"; the magnitude is a fixed
prior, not tuned. Now run on the expanded 2017–2026 sample (with the 2018–19 / 2020 cold-market
IPOs the earlier 2021+ sample lacked), which is a fairer test than before.

Reuses the enhancement harness (``run_arm`` / ``synthesize`` — refit per arm, bootstrap CI, splits)
and ``_paired`` from ``run_b3_gate``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from run_b3_gate import _paired
from run_enhancement_gate import _ReportRow, run_arm, synthesize

from ipo.calibration.dataset import load_records_from_csv
from ipo.calibration.regime import VixSeries
from ipo.core.config import load_config
from ipo.core.types import IPORecord
from ipo.model.scorer import WeightedScorer

_ROOT = Path(__file__).resolve().parents[1]

# Fixed prior weight the VIX read enters the linear score at (GMP-parity: fixed, not fitted; the
# calibrator refit per arm is what adapts). Comparable to a subscription leg's weight.
_W_VIX = 0.10


def main() -> None:
    """Gate India VIX as a weighted score feature on the 358-IPO sample; write the report."""
    config = load_config()
    records = load_records_from_csv(_ROOT / "data" / "backfill" / "mainboard_ipos.csv")
    scorer = WeightedScorer(config.feature_weights, config.features)
    method = config.calibration.method
    cutoff = config.verdict_thresholds.apply
    rc = config.features.regime
    vix = VixSeries(
        _ROOT / "data" / "backfill" / "vix.csv", reference=rc.vix_reference, scale=rc.vix_scale
    )

    def vix_add(rec: IPORecord) -> float | None:
        stress = vix.vol_stress_at(rec.close_date)  # [-1, 1], high VIX = fearful/cold
        # a-priori sign: high VIX -> risk-off -> weaker listing -> lower score (not tuned).
        return None if stress is None else -_W_VIX * stress

    arms: list[tuple[str, Callable[[IPORecord], float | None]]] = [
        ("India VIX (vol-stress at close) as a score feature", vix_add),
    ]
    report: list[_ReportRow] = []
    for name, add_of in arms:
        base, arm, rate = _paired(records, scorer, config, add_of)
        results, prec_wo, prec_w = run_arm(base, arm, method=method, cutoff=cutoff)
        verdict, why = synthesize(name, len(base), results)
        report.append((name, len(base), rate, verdict, why, results, prec_wo, prec_w))
        print(f"\n### {name}: {verdict}  (N={len(base)}, base rate {rate:.0%})")  # noqa: T201
        for r in results:
            print(  # noqa: T201
                f"   {r.initial}/{r.step} OOS={r.n_oos} {'keep' if r.keep else 'cut '} "
                f"AUC {r.auc_wo:.3f}->{r.auc_w:.3f} ECE {r.ece_wo:.3f}->{r.ece_w:.3f} "
                f"lift {r.lift:+.3f} [{r.lo:+.3f},{r.hi:+.3f}]"
            )
    _write_report(_ROOT / "docs" / "B2_SCORE_GATE.md", report, cutoff=cutoff)
    print("\nwrote docs/B2_SCORE_GATE.md")  # noqa: T201


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def _write_report(out: Path, report: list[_ReportRow], *, cutoff: float) -> None:
    lines = [
        "# B2 second half — India VIX as a score feature (gate)",
        "",
        "*The B2 flag-enrichment half already shipped (VIX into the cold flag at weight 0). This "
        "gates the **score-feature** half: VIX entered as a weighted input, scored WITH vs WITHOUT "
        "on the same IPOs, walk-forward OOS, **calibrator refit per arm** (GMP-parity — a fixed "
        "prior weight, not a fitted coefficient), ECE + AUC + a paired-bootstrap CI on the AUC "
        "lift across ≥3 splits. Null hypothesis: **QIB-redundancy** (fear already echoes through "
        "cautious QIB bidding); the burden of proof is on the feature. Expanded 2017–2026 sample. "
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
