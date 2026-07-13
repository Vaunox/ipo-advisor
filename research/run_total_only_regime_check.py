"""Check 2 — cold-market/regime + T+3 stability stress-test for Total-only (research, OFF-MAIN).

Phase-1 deployability check on branch `total-only-gate`. The shipped model was stress-tested
through regime lineage (PROJECT_LOG §4.5) and the T+3 settlement cross-break (§4.6); total_only
has not been. This runs the **identical shipped functions** used for those checks
(``ipo.service.stability.cross_break_stability``, ``ipo.calibration.regime.NiftyRegime``,
``ipo.calibration.reliability.evaluate_reliability``) against the total_only arm from the
earlier comparison gate (``research/TOTAL_ONLY_GATE.md``), at the default 60/20 walk-forward
(the same window §4.1/§4.5/§4.6 report on).

Read-only / comparison only: nothing under ``models/``, ``src/``, or ``config/`` is touched.
The "full" arm is run alongside as a control — it must reproduce the committed §4.5/§4.6 numbers
to validate the harness before trusting the total_only numbers.

Usage: PYTHONPATH=src python research/run_total_only_regime_check.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from research.total_only_variant import build_variant_items, load_total_sub_by_id

from ipo.calibration.backtest import BacktestRow, walk_forward
from ipo.calibration.benchmark import BenchRow, wilson_ci
from ipo.calibration.dataset import load_records_from_csv, scored_items_from_records
from ipo.calibration.label import net_listing_return
from ipo.calibration.regime import NiftyRegime
from ipo.calibration.reliability import evaluate_reliability
from ipo.core.config import CalibrationConfig, SellCosts, load_config
from ipo.model.scorer import WeightedScorer
from ipo.service.stability import cross_break_stability

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CSV = _REPO_ROOT / "data" / "backfill" / "mainboard_ipos.csv"
_NIFTY_CSV = _REPO_ROOT / "data" / "backfill" / "nifty.csv"


def _to_benchrows(
    oos: list[BacktestRow],
    records_by_id: dict,
    totals: dict[str, float],
    *,
    sell_costs: SellCosts,
    nominal_application_value: float,
) -> list[BenchRow]:
    """Join a variant's walk-forward OOS rows with real net-return/qib/total from records."""
    rows: list[BenchRow] = []
    for r in oos:
        rec = records_by_id.get(r.ipo_id)
        if rec is None or rec.qib_sub is None or rec.listing_open is None:
            continue
        if rec.listing_date is None:
            continue
        net = net_listing_return(
            rec.issue_price, rec.listing_open, sell_costs,
            nominal_application_value=nominal_application_value,
        )
        rows.append(
            BenchRow(
                r.ipo_id, rec.listing_date, r.label, net,
                rec.qib_sub, totals.get(rec.ipo_id, rec.qib_sub), r.prob,
            )
        )
    return rows


@dataclass(frozen=True)
class RegimeRow:
    """One row of the §4.5-style regime table."""

    label: str
    n: int
    base_rate: float
    auc: float
    ece: float
    n_apply: int
    apply_precision: float | None
    ci_low: float
    ci_high: float


def _regime_table(
    rows: list[BenchRow], regime: NiftyRegime, *, apply_cutoff: float
) -> list[RegimeRow]:
    """Split OOS rows by Nifty regime-at-listing and compute AUC/ECE/APPLY precision each."""
    buckets = {
        "All": rows,
        "Hot": [r for r in rows if not regime.is_cold(r.listing_date)],
        "Cold": [r for r in rows if regime.is_cold(r.listing_date)],
    }
    out: list[RegimeRow] = []
    for label, rs in buckets.items():
        if not rs:
            out.append(RegimeRow(label, 0, 0.0, 0.0, 0.0, 0, None, 0.0, 0.0))
            continue
        rep = evaluate_reliability([r.model_prob for r in rs], [r.label for r in rs])
        applied = [r for r in rs if r.model_prob >= apply_cutoff]
        if applied:
            pos = sum(r.label for r in applied)
            lo, hi = wilson_ci(pos, len(applied))
            prec: float | None = pos / len(applied)
        else:
            prec, lo, hi = None, 0.0, 0.0
        out.append(
            RegimeRow(label, len(rs), rep.base_rate, rep.auc, rep.ece, len(applied), prec, lo, hi)
        )
    return out


def _print_regime_table(
    name: str, rows: list[BenchRow], regime: NiftyRegime, *, cutoff: float
) -> None:
    print(f"\n{name}:")
    hdr = (
        f"{'Regime':<8}{'N':>5}{'Base':>7}{'AUC':>7}{'ECE':>8}"
        f"{'APPLY N':>9}{'APPLY prec':>12}{'95% CI':>18}"
    )
    print(hdr)
    for row in _regime_table(rows, regime, apply_cutoff=cutoff):
        ci = f"[{row.ci_low:.0%},{row.ci_high:.0%}]" if row.apply_precision is not None else "n/a"
        prec = f"{row.apply_precision:.0%}" if row.apply_precision is not None else "n/a"
        print(f"{row.label:<8}{row.n:>5}{row.base_rate:>7.0%}{row.auc:>7.2f}{row.ece:>8.3f}"
              f"{row.n_apply:>9}{prec:>12}{ci:>18}")


def _print_t3(name: str, rows: list[BenchRow], *, cutoff: float, cal: CalibrationConfig) -> None:
    stab = cross_break_stability(rows, apply_cutoff=cutoff, n_bins=cal.n_buckets)
    print(f"\n{name}: {stab.verdict}")

    def _prec(snap: object) -> str:
        p = snap.apply_precision  # type: ignore[attr-defined]
        if p is None:
            return "n/a"
        return f"{p:.0%} (n={snap.n_apply})"  # type: ignore[attr-defined]

    print(
        f"  pre-T+3  (< {stab.cutover.isoformat()}): n={stab.pre.n} "
        f"base={stab.pre.base_rate:.0%} ECE={stab.pre.ece:.3f} APPLY_prec={_prec(stab.pre)}"
    )
    print(
        f"  post-T+3 (>= {stab.cutover.isoformat()}): n={stab.post.n} "
        f"base={stab.post.base_rate:.0%} ECE={stab.post.ece:.3f} APPLY_prec={_prec(stab.post)}"
    )
    print(f"  ECE shift: {stab.ece_shift:+.3f} (tolerance {stab.ece_tolerance:.3f})")


def main() -> None:
    """Run the regime + T+3 stress-tests for full (control) and total_only, print both."""
    config = load_config(env=None)
    cal = config.calibration
    scorer = WeightedScorer(config.feature_weights, config.features)
    cutoff = config.verdict_thresholds.apply
    initial, step = cal.walk_forward_initial, cal.walk_forward_step

    records = load_records_from_csv(_CSV)
    records_by_id = {r.ipo_id: r for r in records}
    full_items = scored_items_from_records(
        records, scorer, features_config=config.features, sell_costs=config.sell_costs,
        nominal_application_value=cal.nominal_application_value,
    )
    totals = load_total_sub_by_id(_CSV)
    _, total_items = build_variant_items(
        full_items, records, scorer=scorer, features_config=config.features, totals=totals
    )

    full_oos = walk_forward(full_items, cal.method, initial=initial, step=step)
    total_oos = walk_forward(total_items, cal.method, initial=initial, step=step)
    full_rows = _to_benchrows(
        full_oos, records_by_id, totals,
        sell_costs=config.sell_costs, nominal_application_value=cal.nominal_application_value,
    )
    total_rows = _to_benchrows(
        total_oos, records_by_id, totals,
        sell_costs=config.sell_costs, nominal_application_value=cal.nominal_application_value,
    )

    regime = NiftyRegime(_NIFTY_CSV)

    print("=" * 88)
    print("REGIME STRESS-TEST (PROJECT_LOG §4.5-style) — default 60/20 walk-forward")
    print("full is the CONTROL: must reproduce the committed Stage-2 358-sample numbers")
    print("(All 298/70%/0.80/0.081 | Hot 193/75%/0.80/0.077 | Cold 105/60%/0.76/0.102)")
    print("=" * 88)
    _print_regime_table("full (control)", full_rows, regime, cutoff=cutoff)
    _print_regime_table("total_only", total_rows, regime, cutoff=cutoff)

    print()
    print("=" * 88)
    print("T+3 SETTLEMENT CROSS-BREAK STABILITY (PROJECT_LOG §4.6-style)")
    print("full is the CONTROL: must reproduce the committed 358-sample numbers")
    print("(pre n=117 base 73% ECE 0.134 | post n=181 base 68% ECE 0.075 | shift -0.060)")
    print("=" * 88)
    _print_t3("full (control)", full_rows, cutoff=cutoff, cal=cal)
    _print_t3("total_only", total_rows, cutoff=cutoff, cal=cal)


if __name__ == "__main__":
    main()
