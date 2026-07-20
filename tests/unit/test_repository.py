"""ParquetRepository: round-trip, idempotent upsert, incremental, labels."""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

import pytest

from ipo.core.constants import IST
from ipo.core.types import IPORecord, ListingLabel, Segment
from ipo.data.store.repository import _LABELS_FILE, _RECORDS_FILE, ParquetRepository


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


def _label(ipo_id: str) -> ListingLabel:
    return ListingLabel(
        ipo_id=ipo_id,
        issue_price=100.0,
        listing_open=120.0,
        listing_close=130.0,
        listing_return_open=0.2,
        listing_return_close=0.3,
    )


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


# --- Durability (code review #2: atomic write + crash-safe read) -------------


def _corrupt(path: Path) -> None:
    path.write_bytes(b"not a parquet file")  # garbage/torn -> pyarrow.ArrowInvalid on read


def test_corrupt_records_degrades_to_empty_and_flags(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _corrupt(tmp_path / _RECORDS_FILE)
    with caplog.at_level(logging.WARNING):
        repo = ParquetRepository(tmp_path)  # must NOT raise (vm/server builds one per request)

    assert repo.list_all() == []  # degraded to empty, not a crash / 500
    assert repo.records_degraded is True  # corruption stays distinguishable from genuine absence
    warned = [r for r in caplog.records if r.getMessage() == "records_read_failed"]
    assert len(warned) == 1  # loud, not silent


def test_genuinely_empty_is_not_flagged_degraded(tmp_path: Path) -> None:
    repo = ParquetRepository(tmp_path)  # no records file at all — a fresh install

    assert repo.list_all() == []
    assert repo.records_degraded is False  # empty-but-fine must NEVER read as corruption


def test_atomic_write_leaves_no_tmp(tmp_path: Path) -> None:
    repo = ParquetRepository(tmp_path)
    repo.upsert(_record("acme"))
    repo.save_labels([_label("acme")])

    assert list(tmp_path.glob("*.tmp")) == []  # os.replace cleaned up both atomic writes


def test_corrupt_records_healed_by_next_write(tmp_path: Path) -> None:
    _corrupt(tmp_path / _RECORDS_FILE)
    repo = ParquetRepository(tmp_path)  # degraded
    assert repo.records_degraded is True

    repo.upsert(_record("acme"))  # the next atomic write overwrites the corrupt file

    reopened = ParquetRepository(tmp_path)
    assert [r.ipo_id for r in reopened.list_all()] == ["acme"]  # readable again
    assert reopened.records_degraded is False  # healed
    assert list(tmp_path.glob("*.tmp")) == []


def test_corrupt_labels_degrades_to_empty(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _corrupt(tmp_path / _LABELS_FILE)
    with caplog.at_level(logging.WARNING):
        loaded = ParquetRepository(tmp_path).load_labels()  # must NOT raise

    assert loaded == []
    assert [r for r in caplog.records if r.getMessage() == "labels_read_failed"]
