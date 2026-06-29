"""CsvSeedSource: enumeration, fetch/parse round-trip, fail-loud validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipo.data.sources.base import SourceError
from ipo.data.sources.csv_seed import CsvSeedSource

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SEED = _REPO_ROOT / "seed" / "mainboard_ipos.csv"


def test_seed_loads_and_enumerates() -> None:
    source = CsvSeedSource(_SEED)
    ids = source.ipo_ids()
    assert "tatatech-2023" in ids
    assert "spectrum-sme-2023" in ids
    assert len(ids) >= 5


def test_fetch_parse_roundtrip_types() -> None:
    source = CsvSeedSource(_SEED)
    raw = source.fetch("tatatech-2023")
    partial = source.parse(raw)
    f = partial.fields
    assert partial.ipo_id == "tatatech-2023"
    assert f["segment"] == "mainboard"
    assert f["price_band_high"] == 500.0
    assert f["lot_size"] == 30
    assert f["promoter_litigation"] is False
    assert f["listing_open"] == 1200.0


def test_blank_optional_becomes_none() -> None:
    source = CsvSeedSource(_SEED)
    partial = source.parse(source.fetch("zomato-2021"))
    # Zomato was loss-making: no issue P/E in the seed.
    assert partial.fields["issue_pe"] is None


def test_deferred_issue_has_no_listing() -> None:
    source = CsvSeedSource(_SEED)
    partial = source.parse(source.fetch("deferred-co-2024"))
    assert partial.fields["listing_open"] is None
    assert partial.fields["listing_date"] is None


def test_unknown_ipo_id_raises() -> None:
    source = CsvSeedSource(_SEED)
    with pytest.raises(SourceError):
        source.fetch("does-not-exist")


def test_missing_required_column_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("ipo_id,name\nx,X Ltd\n", encoding="utf-8")
    with pytest.raises(SourceError):
        CsvSeedSource(bad)


def test_duplicate_ipo_id_raises(tmp_path: Path) -> None:
    header = (
        "ipo_id,name,segment,price_band_low,price_band_high,lot_size,"
        "issue_size_cr,open_date,close_date\n"
    )
    row = "dup,X Ltd,mainboard,90,100,10,50,2024-01-01,2024-01-03\n"
    dup = tmp_path / "dup.csv"
    dup.write_text(header + row + row, encoding="utf-8")
    with pytest.raises(SourceError):
        CsvSeedSource(dup)


def test_parse_rejects_row_missing_required_value(tmp_path: Path) -> None:
    header = (
        "ipo_id,name,segment,price_band_low,price_band_high,lot_size,"
        "issue_size_cr,open_date,close_date\n"
    )
    row = "x,X Ltd,mainboard,90,100,10,50,2024-01-01,\n"  # blank close_date
    csv_path = tmp_path / "s.csv"
    csv_path.write_text(header + row, encoding="utf-8")
    source = CsvSeedSource(csv_path)
    with pytest.raises(SourceError):
        source.parse(source.fetch("x"))
