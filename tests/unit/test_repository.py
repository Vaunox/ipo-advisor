"""ParquetRepository: round-trip, idempotent upsert, incremental, labels."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from ipo.core.constants import IST
from ipo.core.types import IPORecord, ListingLabel, Segment
from ipo.data.store.repository import ParquetRepository


def _record(ipo_id: str, **overrides: object) -> IPORecord:
    kwargs: dict[str, object] = dict(
        ipo_id=ipo_id,
        name=f"{ipo_id} Ltd",
        segment=Segment.MAINBOARD,
        price_band_low=90.0,
        price_band_high=100.0,
        lot_size=150,
        issue_size_cr=500.0,
        open_date=date(2024, 1, 1),
        close_date=date(2024, 1, 3),
        captured_at=datetime(2024, 1, 3, 18, tzinfo=IST),
    )
    kwargs.update(overrides)
    return IPORecord(**kwargs)  # type: ignore[arg-type]


def test_roundtrip_persists_across_reopen(tmp_path: Path) -> None:
    repo = ParquetRepository(tmp_path)
    repo.upsert(_record("acme", qib_sub=12.5, listing_open=120.0, listing_close=130.0))
    reopened = ParquetRepository(tmp_path)
    got = reopened.get("acme")
    assert got is not None
    assert got.qib_sub == 12.5
    assert got.listing_open == 120.0
    assert got.segment is Segment.MAINBOARD


def test_upsert_is_idempotent(tmp_path: Path) -> None:
    repo = ParquetRepository(tmp_path)
    repo.upsert(_record("acme"))
    repo.upsert(_record("acme", issue_size_cr=999.0))  # same id -> update, not duplicate
    assert len(repo.list_all()) == 1
    assert repo.get("acme").issue_size_cr == 999.0  # type: ignore[union-attr]


def test_incremental_upsert_many(tmp_path: Path) -> None:
    repo = ParquetRepository(tmp_path)
    repo.upsert(_record("a"))
    repo.upsert_many([_record("b"), _record("c")])
    assert {r.ipo_id for r in repo.list_all()} == {"a", "b", "c"}
    # Reopen to confirm the incremental write persisted.
    assert len(ParquetRepository(tmp_path).list_all()) == 3


def test_labels_save_and_load(tmp_path: Path) -> None:
    repo = ParquetRepository(tmp_path)
    labels = [
        ListingLabel(
            ipo_id="acme",
            issue_price=100.0,
            listing_open=120.0,
            listing_close=130.0,
            listing_return_open=0.2,
            listing_return_close=0.3,
        )
    ]
    repo.save_labels(labels)
    loaded = ParquetRepository(tmp_path).load_labels()
    assert len(loaded) == 1
    assert loaded[0].listing_return_open == 0.2


def test_load_labels_empty_when_none(tmp_path: Path) -> None:
    assert ParquetRepository(tmp_path).load_labels() == []
