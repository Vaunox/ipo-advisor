"""Benchmark the calibrated model vs simple subscription rules (full Phase-4 discipline).

Walk-forward out-of-sample, no tuning on the reported fold. Prints and writes
``docs/BENCHMARK.md``: the five selectors' APPLY precision (+ Wilson CIs + N),
loss profiles, a paired model-vs-QIB comparison, a regime (cold-slice) split, and
the calibration the rules cannot provide.

Usage:
    python scripts/run_benchmark.py [--env dev|prod] [--csv PATH]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ipo.calibration.benchmark import (
    MethodResult,
    by_year,
    killflag_firings,
    load_oos_rows,
    mcnemar,
    select_methods,
)
from ipo.calibration.benchmark import _result as method_result
from ipo.calibration.reliability import evaluate_reliability
from ipo.core.config import load_config
from ipo.model.scorer import WeightedScorer

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LABELS = {
    "apply_all": "Apply to all (base rate)",
    "total_gt_1x": "Apply if overall subscription > 1x",
    "qib_gt_1x": "Apply if QIB > 1x",
    "top_n_qib": "Top-N by QIB (equal selectivity)",
    "model_apply": "Model APPLY verdicts",
}
_ORDER = ["apply_all", "total_gt_1x", "qib_gt_1x", "top_n_qib", "model_apply"]


def _fmt(r: MethodResult) -> str:
    prec = "n/a" if r.precision is None else f"{r.precision:.1%}"
    flop = "n/a" if r.mean_flop_net is None else f"{r.mean_flop_net:+.1%}"
    return (
        f"| {_LABELS[r.name]} | {r.n_selected} | {prec} | "
        f"[{r.ci_low:.1%}, {r.ci_high:.1%}] | {r.n_flops} | {flop} |"
    )


def main() -> None:
    """Run the benchmark and write the report."""
    parser = argparse.ArgumentParser(description="Benchmark model vs subscription rules.")
    parser.add_argument("--env", default=None)
    parser.add_argument("--csv", default="data/backfill/mainboard_ipos.csv")
    args = parser.parse_args()

    config = load_config(env=args.env)
    cal = config.calibration
    cutoff = config.verdict_thresholds.apply
    scorer = WeightedScorer(config.feature_weights, config.features)

    rows = load_oos_rows(
        _REPO_ROOT / args.csv,
        scorer=scorer,
        features_config=config.features,
        sell_costs=config.sell_costs,
        nominal_application_value=cal.nominal_application_value,
        method=cal.method,
        initial=cal.walk_forward_initial,
        step=cal.walk_forward_step,
    )
    sel = select_methods(rows, apply_cutoff=cutoff)
    results = {name: method_result(name, sel[name]) for name in _ORDER}

    # Paired model vs equal-selectivity QIB rule.
    pair = mcnemar(sel["model_apply"], sel["top_n_qib"], rows)

    # Regime: coldest year with a usable sample.
    years = by_year(rows)
    cold_year = min(
        (y for y, rs in years.items() if len(rs) >= 15),
        key=lambda y: sum(r.label for r in years[y]) / len(years[y]),
        default=None,
    )

    # Calibration the rules cannot provide.
    rel = evaluate_reliability([r.model_prob for r in rows], [r.label for r in rows], cal.n_buckets)

    # Kill-flags among heavily-oversubscribed IPOs the QIB rule would apply to.
    n_high, n_flagged, flag_reasons = killflag_firings(
        _REPO_ROOT / args.csv,
        features_config=config.features,
        killflag_config=config.killflags,
    )

    lines = _build_report(results, pair, years, cold_year, rel, cutoff, len(rows))
    lines += [
        "",
        "## Kill-flags on heavily-oversubscribed IPOs (QIB > 10x)",
        "",
        f"Of {n_high} heavily-oversubscribed mainboard IPOs, **{n_flagged}** tripped a "
        "kill-flag. "
        + (
            f"Examples: {'; '.join(flag_reasons)}."
            if flag_reasons
            else "In the official-only dataset the kill-flag inputs (final-days GMP slope, "
            "OFS fraction) are not yet populated, and SME issues are excluded upstream — so "
            "no kill-flag can fire here. Their loss-avoidance value is demonstrable only once "
            "Phase 5 (GMP) and OFS enrichment land."
        ),
    ]
    (_REPO_ROOT / "docs" / "BENCHMARK.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))  # noqa: T201


def _build_report(
    results: dict[str, MethodResult],
    pair: dict[str, int],
    years: dict[int, list],  # type: ignore[type-arg]
    cold_year: int | None,
    rel: object,
    cutoff: float,
    n_oos: int,
) -> list[str]:
    from ipo.calibration.benchmark import _result as mr
    from ipo.calibration.reliability import ReliabilityReport

    assert isinstance(rel, ReliabilityReport)
    model = results["model_apply"]
    qib_eq = results["top_n_qib"]
    gap = (
        (model.precision - qib_eq.precision)
        if (model.precision is not None and qib_eq.precision is not None)
        else 0.0
    )
    lines = [
        "# Benchmark — Calibrated Model vs Subscription Rules",
        "",
        "*Same walk-forward out-of-sample set, no tuning on the reported fold. "
        "APPLY precision = fraction of selected IPOs that listed positive net-of-cost. "
        "Engineering/research reference, not financial advice.*",
        "",
        f"Out-of-sample IPOs: **{n_oos}** | model APPLY cutoff: {cutoff}",
        "",
        "## APPLY precision (with Wilson 95% CI)",
        "",
        "| Method | N selected | APPLY precision | 95% CI | Losers | Avg loss (net) |",
        "|---|---|---|---|---|---|",
    ]
    lines += [_fmt(results[name]) for name in _ORDER]
    lines += [
        "",
        "## Model vs equal-selectivity QIB rule (the key head-to-head)",
        "",
        f"- Model APPLY precision: **{_pct(model.precision)}** (N={model.n_selected}, "
        f"CI [{model.ci_low:.1%}, {model.ci_high:.1%}])",
        f"- Top-N-by-QIB precision: **{_pct(qib_eq.precision)}** (N={qib_eq.n_selected}, "
        f"CI [{qib_eq.ci_low:.1%}, {qib_eq.ci_high:.1%}])",
        f"- Precision gap: **{gap:+.1%}** "
        + (
            "(CIs overlap heavily — not a real edge)"
            if _overlap(model, qib_eq)
            else "(CIs separate)"
        ),
        "",
        "Paired view (only where the two disagree):",
        f"- IPOs only the model picks: {pair['only_a_picks_winners']} winners / "
        f"{pair['only_a_picks_losers']} losers",
        f"- IPOs only the QIB rule picks: {pair['only_b_picks_winners']} winners / "
        f"{pair['only_b_picks_losers']} losers",
        "",
        "## Calibration — what the rules cannot do",
        "",
        f"The model emits an honest probability (OOS ECE **{rel.ece:.3f}**, Brier "
        f"**{rel.brier:.3f}**, AUC **{rel.auc:.3f}**); the rules emit only yes/no, so "
        "they cannot tell you *how likely* — there is no calibration to report for them.",
        "",
        "| Bin predicted | Observed | N |",
        "|---|---|---|",
    ]
    lines += [f"| {b.mean_predicted:.2f} | {b.observed_rate:.2f} | {b.count} |" for b in rel.bins]
    lines += ["", "## Loss profile (lower / smaller is better)", ""]
    lines += [
        f"- {_LABELS[name]}: {results[name].n_flops} losers, "
        f"avg net {_pct(results[name].mean_flop_net)}, worst {_pct(results[name].worst_flop_net)}"
        for name in _ORDER
    ]
    lines += ["", "## Regime split (does the QIB rule break in a cold market?)", ""]
    lines += [
        "| Year | N | Base rate | QIB>1x prec | Top-N-QIB prec | Model prec |",
        "|---|---|---|---|---|---|",
    ]
    for y, rs in years.items():
        s = select_methods(rs, apply_cutoff=cutoff)
        base = sum(r.label for r in rs) / len(rs)
        qib_p = _pct(mr("", s["qib_gt_1x"]).precision)
        topn_p = _pct(mr("", s["top_n_qib"]).precision)
        model_p = _pct(mr("", s["model_apply"]).precision)
        lines.append(f"| {y} | {len(rs)} | {base:.0%} | {qib_p} | {topn_p} | {model_p} |")
    if cold_year is not None:
        cold = years[cold_year]
        s = select_methods(cold, apply_cutoff=cutoff)
        m, q = mr("", s["model_apply"]), mr("", s["top_n_qib"])
        lines += [
            "",
            f"**Coldest slice = {cold_year}** (base rate "
            f"{sum(r.label for r in cold) / len(cold):.0%}): "
            f"model {_pct(m.precision)} (N={m.n_selected}) vs top-N-QIB {_pct(q.precision)} "
            f"(N={q.n_selected}).",
        ]
    return lines


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def _overlap(a: MethodResult, b: MethodResult) -> bool:
    return not (a.ci_low > b.ci_high or b.ci_low > a.ci_high)


if __name__ == "__main__":
    main()
