"""Assemble the calibration training set from records (shared by script + tests).

Turns ``IPORecord``s into dated ``(score, label)`` pairs using the same point-in-time
feature build, scorer, and net-of-cost label the live engine uses — so the backtest
calibrates exactly what production scores. Records missing the critical QIB feature,
a closed book, or a listing label are excluded (honest abstention, Deep Dive #4).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from ipo.calibration.backtest import ScoredItem
from ipo.calibration.label import is_positive, net_listing_return
from ipo.core.config import FeaturesConfig, SellCosts
from ipo.core.constants import IST
from ipo.core.types import IPORecord, Segment
from ipo.data.hygiene.clean import BadRecordLog, try_build_record
from ipo.data.sources.csv_seed import CsvSeedSource
from ipo.features.build import build_features
from ipo.model.scorer import WeightedScorer


def load_records_from_csv(csv_path: Path) -> list[IPORecord]:
    """Load and validate IPO records from a seed-schema CSV (bad rows are dropped)."""
    source = CsvSeedSource(csv_path)
    bad = BadRecordLog()
    records: list[IPORecord] = []
    for ipo_id in source.ipo_ids():
        partial = source.parse(source.fetch(ipo_id))
        record = try_build_record(ipo_id, partial.fields, source_hashes={}, bad_records=bad)
        if record is not None:
            records.append(record)
    return records


def scored_items_from_records(
    records: list[IPORecord],
    scorer: WeightedScorer,
    *,
    features_config: FeaturesConfig,
    sell_costs: SellCosts,
    nominal_application_value: float,
    market_regime_of: Callable[[date], float | None] | None = None,
) -> list[ScoredItem]:
    """Build dated (score, net-positive-label) items for the eligible mainboard IPOs.

    ``market_regime_of`` is **off by default**: the Phase-4 calibrator is fit on
    regime-free scores and must stay that way. It exists only so live-parity / the
    weight-0 equality guard can populate ``market_regime`` (as-of the close) without
    changing the trained calibrator — proving the regime feature is flag-only.
    """
    items: list[ScoredItem] = []
    for rec in records:
        if rec.segment is not Segment.MAINBOARD or rec.listing_open is None or rec.qib_sub is None:
            continue
        if rec.listing_date is None:
            continue
        asof = datetime(
            rec.close_date.year, rec.close_date.month, rec.close_date.day, 18, tzinfo=IST
        )
        regime = market_regime_of(rec.close_date) if market_regime_of is not None else None
        feats = build_features(rec, asof, market_regime=regime, config=features_config)
        score = scorer.score(feats)
        net = net_listing_return(
            rec.issue_price,
            rec.listing_open,
            sell_costs,
            nominal_application_value=nominal_application_value,
        )
        items.append(ScoredItem(rec.ipo_id, rec.listing_date, score, is_positive(net)))
    return items
