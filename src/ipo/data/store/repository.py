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
import os
from pathlib import Path
from typing import Any, cast

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import ValidationError

from ipo.core.logging import get_logger
from ipo.core.types import IPORecord, ListingLabel

_log = get_logger("ipo.data.store.repository")

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


def _write_rows_atomic(rows: list[dict[str, Any]], path: Path) -> None:
    """Write ``rows`` as Parquet via tmp + ``os.replace`` — a crash never leaves a torn file.

    The old direct ``pq.write_table`` onto the live path is the torn-parquet corruption the code
    review raised as #2: an interrupted write truncated the whole store, which ``vm/server.py`` then
    failed to read on every request. ``os.replace`` swaps atomically, so a concurrent reader / a
    crash sees either the whole old file or the whole new one — never a partial.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(pa.Table.from_pylist(rows), tmp)  # type: ignore[no-untyped-call]
    os.replace(tmp, path)


class ParquetRepository:
    """Idempotent Parquet store for ``IPORecord``s plus a listing-label table."""

    def __init__(self, data_dir: Path) -> None:
        """Open (or create) the store under ``data_dir`` and load records into memory.

        A corrupt/torn records file must not crash the reader: ``vm/server.py`` builds a fresh
        ``ParquetRepository`` per request, so an unguarded read would turn one torn write into a
        permanent per-request outage (the code review's #2). Instead the load degrades to an empty
        store, sets ``records_degraded`` (so the caller can tell corruption from genuine absence),
        and logs loudly; the next atomic write heals the file. The read stays side-effect-free — no
        quarantine — because the records store is reproducible (re-scraped every ingest cycle).
        """
        self._dir = data_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._records_path = data_dir / _RECORDS_FILE
        self._labels_path = data_dir / _LABELS_FILE
        self._records: dict[str, IPORecord] = {}
        # True ONLY when a corrupt records file forced an empty load — NEVER on a genuinely empty
        # store. Lets the /records route null a stale ``refreshed_at`` on corruption while keeping
        # it for a real-but-empty ingest (freshness honesty — composes with the parked review #6).
        self.records_degraded: bool = False
        if self._records_path.is_file():
            try:
                for row in _read_rows(self._records_path):
                    record = _row_to_record(row)
                    self._records[record.ipo_id] = record
            except (OSError, ValueError, ValidationError) as exc:
                self._records = {}  # drop any partial load — degrade to a clean, empty store
                self.records_degraded = True
                _log.warning(
                    "records_read_failed",
                    extra={"path": str(self._records_path), "error": str(exc)},
                )

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
        """Persist the listing-label table (full rewrite, atomic)."""
        rows = [label.model_dump(mode="json") for label in labels]
        if not rows:
            return
        _write_rows_atomic(rows, self._labels_path)

    def load_labels(self) -> list[ListingLabel]:
        """Load the listing-label table (empty if none persisted or unreadable).

        A corrupt labels table degrades to empty + a loud WARN, like the records read — never a
        crash. Labels carry no freshness stamp, so there is no ``refreshed_at`` to null here.
        """
        if not self._labels_path.is_file():
            return []
        try:
            return [ListingLabel.model_validate(row) for row in _read_rows(self._labels_path)]
        except (OSError, ValueError, ValidationError) as exc:
            _log.warning(
                "labels_read_failed",
                extra={"path": str(self._labels_path), "error": str(exc)},
            )
            return []

    # --- Internals ----------------------------------------------------------

    def _flush_records(self) -> None:
        rows = [_record_to_row(record) for record in self._records.values()]
        if not rows:
            return
        _write_rows_atomic(rows, self._records_path)
