"""Hygiene: segment tagging, cross-source merge/conflict, bad-record routing."""

from __future__ import annotations

import pytest

from ipo.core.types import PartialRecord, Segment
from ipo.data.hygiene.clean import (
    BadRecordLog,
    is_mainboard,
    merge_partials,
    normalize_segment,
    try_build_record,
)

_OFFICIAL_FIELDS = frozenset({"listing_close", "qib_sub", "segment"})
_PRIORITY = ["csv_seed", "chittorgarh"]

_VALID_FIELDS: dict[str, object] = {
    "name": "Acme Ltd",
    "segment": "mainboard",
    "price_band_low": 90.0,
    "price_band_high": 100.0,
    "lot_size": 150,
    "issue_size_cr": 500.0,
    "open_date": "2024-01-01",
    "close_date": "2024-01-03",
}


def test_normalize_segment() -> None:
    assert normalize_segment("Mainboard") is Segment.MAINBOARD
    assert normalize_segment("sme") is Segment.SME
    with pytest.raises(ValueError):
        normalize_segment("nonsense")


def test_merge_prefers_higher_priority_source() -> None:
    official = PartialRecord(source="csv_seed", ipo_id="x", fields={"price_band_high": 100.0})
    aggregator = PartialRecord(source="chittorgarh", ipo_id="x", fields={"price_band_high": 999.0})
    result = merge_partials(
        [aggregator, official],
        cross_check_fields=_OFFICIAL_FIELDS,
        source_priority=_PRIORITY,
    )
    assert result.fields["price_band_high"] == 100.0  # csv_seed wins


def test_cross_check_conflict_recorded() -> None:
    official = PartialRecord(source="csv_seed", ipo_id="x", fields={"listing_close": 130.0})
    aggregator = PartialRecord(source="chittorgarh", ipo_id="x", fields={"listing_close": 200.0})
    result = merge_partials(
        [official, aggregator],
        cross_check_fields=_OFFICIAL_FIELDS,
        source_priority=_PRIORITY,
    )
    assert result.fields["listing_close"] == 130.0
    assert len(result.conflicts) == 1
    assert "listing_close" in result.conflicts[0]


def test_matching_values_within_tolerance_no_conflict() -> None:
    a = PartialRecord(source="csv_seed", ipo_id="x", fields={"listing_close": 130.0})
    b = PartialRecord(source="chittorgarh", ipo_id="x", fields={"listing_close": 130.05})
    result = merge_partials([a, b], cross_check_fields=_OFFICIAL_FIELDS, source_priority=_PRIORITY)
    assert result.conflicts == []


def test_try_build_record_valid() -> None:
    bad = BadRecordLog()
    record = try_build_record("acme", dict(_VALID_FIELDS), source_hashes={}, bad_records=bad)
    assert record is not None
    assert is_mainboard(record)
    assert len(bad) == 0


def test_try_build_record_sme_tagged() -> None:
    bad = BadRecordLog()
    fields = dict(_VALID_FIELDS, segment="sme")
    record = try_build_record("sme-co", fields, source_hashes={}, bad_records=bad)
    assert record is not None
    assert record.segment is Segment.SME
    assert not is_mainboard(record)


def test_try_build_record_invalid_routes_to_bad_log() -> None:
    bad = BadRecordLog()
    fields = dict(_VALID_FIELDS, price_band_low=200.0)  # low > high -> invalid
    record = try_build_record("acme", fields, source_hashes={}, bad_records=bad)
    assert record is None
    assert len(bad) == 1
    assert bad.entries[0][0] == "acme"


def test_extra_source_fields_are_dropped() -> None:
    bad = BadRecordLog()
    fields = dict(_VALID_FIELDS, listing_gain_pct=11.49)  # aggregator-only key
    record = try_build_record("acme", fields, source_hashes={}, bad_records=bad)
    assert record is not None  # extra key dropped, not a validation error
