"""Point-in-time leakage firewall utilities (Deep Dive #4 §B).

The single most important invariant in the system: a feature must depend only on
data known at or before the decision time, and the listing-day label must never
inform an input. These helpers make that invariant *testable* — the CI leakage suite
uses them, and so can the Phase-4 backtest before it trusts any score.

The check is behavioural: build features, then build them again from a record whose
**post-decision / label fields have been mutated to sentinels**. A point-in-time-safe
builder yields identical features; a leaky one (peeking at the listing price) differs.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from ipo.core.types import IPOFeatures, IPORecord

# A builder bound to its as-of clock and any side inputs: record -> features.
FeatureBuilder = Callable[[IPORecord, datetime], IPOFeatures]


def future_mutated_record(record: IPORecord) -> IPORecord:
    """Return a copy with all post-decision/label fields set to obvious sentinels.

    A point-in-time-safe feature build must be invariant to these fields, because at
    the decision time they are unknown. The listing date stays on/after the close so
    the record remains valid.
    """
    listing_date = record.listing_date or (record.close_date + timedelta(days=30))
    return record.model_copy(
        update={
            "listing_open": (record.listing_open or 1.0) + 9_999.0,
            "listing_close": (record.listing_close or 1.0) + 9_999.0,
            "listing_date": listing_date,
        }
    )


def is_point_in_time_safe(build: FeatureBuilder, record: IPORecord, asof: datetime) -> bool:
    """True if ``build`` ignores post-decision/label fields (no leakage).

    Compares features built from the real record against features built from a
    future-mutated record; equality means the label cannot have leaked in.
    """
    base = build(record, asof)
    mutated = build(future_mutated_record(record), asof)
    return base.model_dump() == mutated.model_dump()
