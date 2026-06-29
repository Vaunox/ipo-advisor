"""Benchmark the calibrated model against simple subscription rules (Phase-4 honesty).

Same out-of-sample walk-forward set, no tuning on the reported fold. Compares APPLY
precision (fraction of selected IPOs that listed positive net-of-cost) for five
selectors, with Wilson confidence intervals so real gaps separate from noise; then
goes beyond precision to calibration, loss profiles, and a regime (cold-slice) split.

The honest question this answers: does the model beat an equal-selectivity QIB rule
by a meaningful margin — and if not, is its value the honest probability and
loss-avoidance rather than higher precision?
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ipo.calibration.backtest import walk_forward
from ipo.calibration.dataset import load_records_from_csv, scored_items_from_records
from ipo.calibration.label import is_positive, net_listing_return
from ipo.core.config import FeaturesConfig, SellCosts
from ipo.core.types import Segment
from ipo.model.scorer import WeightedScorer


@dataclass(frozen=True)
class BenchRow:
    """One out-of-sample IPO with everything the benchmark needs."""

    ipo_id: str
    listing_date: date
    label: int  # 1 if listed positive net-of-cost
    net_return: float  # net-of-cost listing-day return (fraction)
    qib: float
    total: float
    model_prob: float  # calibrated, out-of-sample (walk-forward)


@dataclass(frozen=True)
class MethodResult:
    """APPLY-precision result for one selector, with a Wilson 95% interval."""

    name: str
    n_selected: int
    positives: int
    precision: float | None
    ci_low: float
    ci_high: float
    n_flops: int
    mean_flop_net: float | None  # average net return among the selected losers
    worst_flop_net: float | None


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% interval for a binomial proportion k/n (robust on small n)."""
    if n == 0:
        return (0.0, 0.0)
    phat = k / n
    denom = 1.0 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def _result(name: str, selected: list[BenchRow]) -> MethodResult:
    n = len(selected)
    positives = sum(r.label for r in selected)
    flops = [r for r in selected if r.label == 0]
    lo, hi = wilson_ci(positives, n)
    return MethodResult(
        name=name,
        n_selected=n,
        positives=positives,
        precision=(positives / n if n else None),
        ci_low=lo,
        ci_high=hi,
        n_flops=len(flops),
        mean_flop_net=(sum(r.net_return for r in flops) / len(flops) if flops else None),
        worst_flop_net=(min((r.net_return for r in flops), default=None)),
    )


def load_oos_rows(
    csv_path: Path,
    *,
    scorer: WeightedScorer,
    features_config: FeaturesConfig,
    sell_costs: SellCosts,
    nominal_application_value: float,
    method: str,
    initial: int,
    step: int,
) -> list[BenchRow]:
    """Build the out-of-sample rows: model probs (walk-forward) joined with subscription."""
    records = load_records_from_csv(csv_path)
    items = scored_items_from_records(
        records,
        scorer,
        features_config=features_config,
        sell_costs=sell_costs,
        nominal_application_value=nominal_application_value,
    )
    eligible = {it.ipo_id for it in items}

    totals: dict[str, float] = {}
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("total_sub"):
                totals[row["ipo_id"]] = float(row["total_sub"])

    meta: dict[str, tuple[float, float, int, float, date]] = {}
    for rec in records:
        if rec.ipo_id not in eligible or rec.segment is not Segment.MAINBOARD:
            continue
        if rec.qib_sub is None or rec.listing_open is None or rec.listing_date is None:
            continue
        net = net_listing_return(
            rec.issue_price,
            rec.listing_open,
            sell_costs,
            nominal_application_value=nominal_application_value,
        )
        meta[rec.ipo_id] = (
            rec.qib_sub,
            totals.get(rec.ipo_id, rec.qib_sub),  # fall back to QIB if total absent
            is_positive(net),
            net,
            rec.listing_date,
        )

    oos_probs = walk_forward(items, method, initial=initial, step=step)
    rows: list[BenchRow] = []
    for r in oos_probs:
        if r.ipo_id not in meta:
            continue
        qib, total, label, net, listing_date = meta[r.ipo_id]
        rows.append(BenchRow(r.ipo_id, listing_date, label, net, qib, total, r.prob))
    return rows


def select_methods(rows: list[BenchRow], *, apply_cutoff: float) -> dict[str, list[BenchRow]]:
    """Return each method's selected IPOs over the out-of-sample set."""
    model = [r for r in rows if r.model_prob >= apply_cutoff]
    n_model = len(model)
    # Equal-selectivity QIB rule: the top-N IPOs by QIB, N = model's APPLY count.
    top_n_qib = sorted(rows, key=lambda r: r.qib, reverse=True)[:n_model]
    return {
        "apply_all": list(rows),
        "total_gt_1x": [r for r in rows if r.total > 1.0],
        "qib_gt_1x": [r for r in rows if r.qib > 1.0],
        "top_n_qib": top_n_qib,
        "model_apply": model,
    }


def mcnemar(
    sel_a: list[BenchRow], sel_b: list[BenchRow], all_rows: list[BenchRow]
) -> dict[str, int]:
    """Paired disagreement between two selectors (who's right where they differ)."""
    a_ids = {r.ipo_id for r in sel_a}
    b_ids = {r.ipo_id for r in sel_b}
    only_a_correct = sum(
        1 for r in all_rows if r.ipo_id in a_ids and r.ipo_id not in b_ids and r.label == 1
    )
    only_a_wrong = sum(
        1 for r in all_rows if r.ipo_id in a_ids and r.ipo_id not in b_ids and r.label == 0
    )
    only_b_correct = sum(
        1 for r in all_rows if r.ipo_id in b_ids and r.ipo_id not in a_ids and r.label == 1
    )
    only_b_wrong = sum(
        1 for r in all_rows if r.ipo_id in b_ids and r.ipo_id not in a_ids and r.label == 0
    )
    return {
        "only_a_picks_winners": only_a_correct,
        "only_a_picks_losers": only_a_wrong,
        "only_b_picks_winners": only_b_correct,
        "only_b_picks_losers": only_b_wrong,
    }


def by_year(rows: list[BenchRow]) -> dict[int, list[BenchRow]]:
    """Group out-of-sample rows by listing year (the regime axis)."""
    grouped: dict[int, list[BenchRow]] = defaultdict(list)
    for r in rows:
        grouped[r.listing_date.year].append(r)
    return dict(sorted(grouped.items()))


def killflag_firings(
    csv_path: Path,
    *,
    features_config: FeaturesConfig,
    killflag_config: object,
    high_qib_threshold: float = 10.0,
) -> tuple[int, int, list[str]]:
    """Count kill-flags among heavily-oversubscribed IPOs the QIB rule would apply to.

    Returns (n_high_qib, n_with_killflag, sample_reasons). In the official-only dataset
    the kill-flag inputs (final-days GMP slope, OFS fraction) are not yet populated, so
    this is expected to be zero — it engages once Phase 5 (GMP) and OFS enrichment land.
    """
    from datetime import datetime

    from ipo.core.config import KillFlagConfig
    from ipo.core.constants import IST
    from ipo.features.build import build_features
    from ipo.model.killflags import kill_flags

    assert isinstance(killflag_config, KillFlagConfig)
    records = load_records_from_csv(csv_path)
    n_high = 0
    n_flagged = 0
    reasons: list[str] = []
    for rec in records:
        if (
            rec.segment is not Segment.MAINBOARD
            or rec.qib_sub is None
            or rec.qib_sub < high_qib_threshold
        ):
            continue
        n_high += 1
        asof = datetime(
            rec.close_date.year, rec.close_date.month, rec.close_date.day, 18, tzinfo=IST
        )
        feats = build_features(rec, asof, config=features_config)
        flags = kill_flags(rec, feats, killflag_config)
        if flags:
            n_flagged += 1
            reasons.append(f"{rec.ipo_id}: {','.join(flags)}")
    return n_high, n_flagged, reasons[:5]
