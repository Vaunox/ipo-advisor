"""GATE 1: a full pull builds the IPO + label tables; returns match; SME tagged.

Drives the pipeline end-to-end with the curated seed source into a Parquet store,
then checks idempotency, incrementality, a known IPO's listing return, and SME
tagging.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ipo.core.types import Segment
from ipo.data.hygiene.clean import is_mainboard
from ipo.data.ingest.pipeline import IngestPipeline
from ipo.data.sources.csv_seed import CsvSeedSource
from ipo.data.store.repository import ParquetRepository

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SEED = _REPO_ROOT / "seed" / "mainboard_ipos.csv"
_OFFICIAL_FIELDS = frozenset(
    {
        "listing_open",
        "listing_close",
        "qib_sub",
        "nii_sub",
        "retail_sub",
        "price_band_high",
        "segment",
    }
)


def _pipeline(repo: ParquetRepository, source: CsvSeedSource) -> IngestPipeline:
    return IngestPipeline(
        [source],
        repo,
        cross_check_fields=_OFFICIAL_FIELDS,
        source_priority=["csv_seed", "chittorgarh"],
    )


def test_full_pull_builds_tables_from_scratch(tmp_path: Path) -> None:
    source = CsvSeedSource(_SEED)
    repo = ParquetRepository(tmp_path)
    report = _pipeline(repo, source).run(source.ipo_ids())

    # Every seed row builds a valid record; only listed ones get labels.
    assert report.records_ingested == len(source.ipo_ids())
    assert report.bad_records == []
    listed = [i for i in source.ipo_ids() if i != "deferred-co-2024"]
    assert report.labels_built == len(listed)

    # Tables persist and reload.
    reopened = ParquetRepository(tmp_path)
    assert len(reopened.list_all()) == report.records_ingested
    assert len(reopened.load_labels()) == report.labels_built


def test_known_ipo_listing_return_matches_exchange_figure(tmp_path: Path) -> None:
    source = CsvSeedSource(_SEED)
    repo = ParquetRepository(tmp_path)
    _pipeline(repo, source).run(source.ipo_ids())

    labels = {label.ipo_id: label for label in repo.load_labels()}
    # Tata Technologies: Rs 500 -> Rs 1200 open = +140% (verified public figure).
    assert labels["tatatech-2023"].listing_return_open == pytest.approx(1.40, abs=1e-6)
    # LIC: Rs 949 -> Rs 867.20 open = -8.62% (verified public figure).
    assert labels["lic-2022"].listing_return_open == pytest.approx(-0.0862, abs=1e-3)


def test_sme_issue_is_tagged(tmp_path: Path) -> None:
    source = CsvSeedSource(_SEED)
    repo = ParquetRepository(tmp_path)
    _pipeline(repo, source).run(source.ipo_ids())

    sme = repo.get("spectrum-sme-2023")
    assert sme is not None
    assert sme.segment is Segment.SME
    assert not is_mainboard(sme)

    mainboard_ids = {r.ipo_id for r in repo.list_all() if is_mainboard(r)}
    assert "tatatech-2023" in mainboard_ids
    assert "spectrum-sme-2023" not in mainboard_ids


def test_rerun_is_idempotent(tmp_path: Path) -> None:
    source = CsvSeedSource(_SEED)
    repo = ParquetRepository(tmp_path)
    _pipeline(repo, source).run(source.ipo_ids())
    count_after_first = len(repo.list_all())
    _pipeline(repo, source).run(source.ipo_ids())  # re-run
    assert len(repo.list_all()) == count_after_first  # no duplicates


def test_incremental_update_adds_new_ipo(tmp_path: Path) -> None:
    # Start from a one-row seed, then add a second row and ingest just the new id.
    header = (
        "ipo_id,name,segment,price_band_low,price_band_high,lot_size,issue_size_cr,"
        "ofs_fraction,open_date,close_date,listing_date,qib_sub,nii_sub,retail_sub,"
        "issue_pe,peer_median_pe,promoter_litigation,listing_open,listing_close\n"
    )
    row_a = (
        "a-co,A Ltd,mainboard,90,100,10,50,0.1,"
        "2024-01-01,2024-01-03,2024-01-08,5,3,2,,,false,120,130\n"
    )
    row_b = (
        "b-co,B Ltd,mainboard,90,100,10,50,0.1,"
        "2024-02-01,2024-02-03,2024-02-08,5,3,2,,,false,140,150\n"
    )

    seed = tmp_path / "seed.csv"
    seed.write_text(header + row_a, encoding="utf-8")
    repo = ParquetRepository(tmp_path / "store")
    _pipeline(repo, CsvSeedSource(seed)).run(["a-co"])
    assert {r.ipo_id for r in repo.list_all()} == {"a-co"}

    seed.write_text(header + row_a + row_b, encoding="utf-8")
    _pipeline(repo, CsvSeedSource(seed)).run(["b-co"])  # incremental: only the new id
    assert {r.ipo_id for r in repo.list_all()} == {"a-co", "b-co"}
    assert len(repo.load_labels()) == 2
