"""GATE 2 (integration): features build for a real ingested past IPO, leakage-free.

Ties Layer 1 -> Layer 2: ingest the seed, pull a stored record, build its
point-in-time features as of the subscription close, and assert the leakage firewall
holds on real data.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ipo.core.constants import IST
from ipo.data.ingest.pipeline import IngestPipeline
from ipo.data.sources.csv_seed import CsvSeedSource
from ipo.data.store.repository import ParquetRepository
from ipo.features.build import build_features
from ipo.features.leakage import is_point_in_time_safe

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SEED = _REPO_ROOT / "seed" / "mainboard_ipos.csv"


def _ingest(tmp_path: Path) -> ParquetRepository:
    source = CsvSeedSource(_SEED)
    repo = ParquetRepository(tmp_path)
    IngestPipeline(
        [source],
        repo,
        cross_check_fields=frozenset({"qib_sub", "price_band_high"}),
        source_priority=["csv_seed"],
    ).run(source.ipo_ids())
    return repo


def test_features_build_for_ingested_ipo_as_of_close(tmp_path: Path) -> None:
    repo = _ingest(tmp_path)
    rec = repo.get("tatatech-2023")
    assert rec is not None

    asof = datetime(rec.close_date.year, rec.close_date.month, rec.close_date.day, 18, tzinfo=IST)
    feats = build_features(rec, asof)

    assert feats.book_closed is True
    assert feats.qib_sub == 203.41
    assert feats.relative_valuation == 32.5 / 40.1
    assert feats.ofs_fraction == 1.0
    # GMP scraper is Phase 5: level is absent and explicitly flagged, not zero.
    assert feats.gmp_level is None
    assert "gmp_unavailable" in feats.flags


def test_ingested_features_are_point_in_time_safe(tmp_path: Path) -> None:
    repo = _ingest(tmp_path)
    rec = repo.get("lic-2022")
    assert rec is not None
    asof = datetime(rec.close_date.year, rec.close_date.month, rec.close_date.day, 18, tzinfo=IST)
    assert is_point_in_time_safe(build_features, rec, asof) is True
