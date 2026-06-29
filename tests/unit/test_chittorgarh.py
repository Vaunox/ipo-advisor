"""ChittorgarhSource: real-HTML microdata parse + fail-loud on source drift.

Parses a real captured fixture (the schema.org microdata listing table), so the
test exercises actual markup rather than a hand-made shape.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ipo.core.constants import IST
from ipo.core.types import RawResponse
from ipo.data.sources.base import SourceError
from ipo.data.sources.chittorgarh import ChittorgarhSource, _to_float

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "chittorgarh_recent_ipos.html"


def _raw(content: str) -> RawResponse:
    return RawResponse(
        source="chittorgarh",
        url="https://www.chittorgarh.com/ipo/x/1/",
        fetched_at=datetime(2026, 1, 1, tzinfo=IST),
        content=content,
        content_hash="x",
    )


def _source() -> ChittorgarhSource:
    # Parsing needs no network; client/cache are unused by parse_listing.
    return ChittorgarhSource.__new__(ChittorgarhSource)


def test_to_float_handles_currency_percent_and_commas() -> None:
    assert _to_float("₹1,314.30") == 1314.30
    assert _to_float("+11.49%") == 11.49
    assert _to_float("₹489.95 Cr") == 489.95
    assert _to_float("—") is None


def test_parse_listing_extracts_real_rows() -> None:
    raw = _raw(_FIXTURE.read_text(encoding="utf-8"))
    records = _source().parse_listing(raw)
    assert len(records) == 9

    first = records[0]
    assert first.fields["name"] == "Protean eGov Technologies Ltd."
    assert first.fields["segment"] == "mainboard"
    assert first.fields["issue_size_cr"] == 489.95
    assert first.fields["price_band_high"] == 792.0
    assert first.fields["listing_close"] == 883.0
    assert first.fields["listing_gain_pct"] == 11.49
    assert first.ipo_id == "protean-egov-technologies-ipo-1545"


def test_parse_returns_first_row() -> None:
    raw = _raw(_FIXTURE.read_text(encoding="utf-8"))
    partial = _source().parse(raw)
    assert partial.fields["name"] == "Protean eGov Technologies Ltd."


def test_missing_table_raises_source_error() -> None:
    raw = _raw("<html><body><p>no microdata here</p></body></html>")
    with pytest.raises(SourceError):
        _source().parse_listing(raw)
