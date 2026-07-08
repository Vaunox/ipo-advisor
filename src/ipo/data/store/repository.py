"""Parquet-backed repository for IPO records and listing labels (Layer 1 output).

The store is the small, versioned source of truth the backtest reads. Upserts are
idempotent and keyed on ``ipo_id`` (Deep Dive #1, Module 3): re-running an ingest
never duplicates or silently mutates a row. Data volume is tiny (hundreds of IPOs),
so the whole table is held in memory and rewritten on flush — the simplest design
that guarantees idempotency.

Nested fields (``anchor_book``, ``source_hashes``) are stored as JSON strings; all
other fields are columnar scalars. Round-tripping is exact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pyarrow as pa
import pyarrow.parquet as pq

from ipo.core.types import IPORecord, ListingLabel

_RECORDS_FILE = "ipo_records.parquet"
_LABELS_FILE = "listing_labels.parquet"


def _record_to_row(record: IPORecord) -> dict[str, Any]:
    row = record.model_dump(mode="json")
    row["anchor_book"] = json.dumps(row["anchor_book"]) if row["anchor_book"] is not None else None
    row["source_hashes"] = json.dumps(row["source_hashes"])
    return row


def _row_to_record(row: dict[str, Any]) -> IPORecord:
    data = dict(row)
    anchor = data.get("anchor_book")
    data["anchor_book"] = json.loads(anchor) if anchor else None
    data.pop("subscription_progression", None)  # legacy column (feature removed) — drop if present
    hashes = data.get("source_hashes")
    data["source_hashes"] = json.loads(hashes) if hashes else {}
    return IPORecord.model_validate(data)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    # pyarrow.parquet ships only partial type info; calls are untyped to mypy.
    table = pq.read_table(path)  # type: ignore[no-untyped-call]
    return cast(list[dict[str, Any]], table.to_pylist())


class ParquetRepository:
    """Idempotent Parquet store for ``IPORecord``s plus a listing-label table."""

    def __init__(self, data_dir: Path) -> None:
        """Open (or create) the store under ``data_dir`` and load records into memory."""
        self._dir = data_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._records_path = data_dir / _RECORDS_FILE
        self._labels_path = data_dir / _LABELS_FILE
        self._records: dict[str, IPORecord] = {}
        if self._records_path.is_file():
            for row in _read_rows(self._records_path):
                record = _row_to_record(row)
                self._records[record.ipo_id] = record

    # --- Repository protocol ------------------------------------------------

    def upsert(self, record: IPORecord) -> None:
        """Insert or update one record (idempotent), then flush."""
        self._records[record.ipo_id] = record
        self._flush_records()

    def get(self, ipo_id: str) -> IPORecord | None:
        """Return the record for ``ipo_id``, or ``None``."""
        return self._records.get(ipo_id)

    def list_all(self) -> list[IPORecord]:
        """Return every stored record."""
        return list(self._records.values())

    # --- Bulk / label helpers ----------------------------------------------

    def upsert_many(self, records: list[IPORecord]) -> None:
        """Upsert many records with a single flush (incremental-pull friendly)."""
        for record in records:
            self._records[record.ipo_id] = record
        self._flush_records()

    def save_labels(self, labels: list[ListingLabel]) -> None:
        """Persist the listing-label table (full rewrite)."""
        rows = [label.model_dump(mode="json") for label in labels]
        if not rows:
            return
        pq.write_table(pa.Table.from_pylist(rows), self._labels_path)  # type: ignore[no-untyped-call]

    def load_labels(self) -> list[ListingLabel]:
        """Load the listing-label table (empty if none persisted)."""
        if not self._labels_path.is_file():
            return []
        return [ListingLabel.model_validate(row) for row in _read_rows(self._labels_path)]

    # --- Internals ----------------------------------------------------------

    def _flush_records(self) -> None:
        rows = [_record_to_row(record) for record in self._records.values()]
        if not rows:
            return
        pq.write_table(pa.Table.from_pylist(rows), self._records_path)  # type: ignore[no-untyped-call]
