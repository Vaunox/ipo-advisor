"""Append-only Parquet bank for day-wise subscription polls (v2 A1, collect-forward).

Official day-by-day subscription buildup is not reliably archived for free, so it is
*collected forward*: the recorder polls NSE through each open book and appends one
``DaywiseSubscriptionRow`` per genuinely-new observation. This store is the durable home
for those rows, and its discipline is the whole point of collecting our own history —

* **append-only, never overwrite.** A banked observation is immutable; a second write of
  the same natural key ``(ipo_id, captured_at)`` is a no-op. Overwrite a row and you have
  rebuilt exactly the point-in-time-blind data the aggregators already have (Deep Dive #B).
* **idempotent.** Re-running the recorder over the same snapshot duplicates nothing —
  the natural key dedupes replays, and the recorder additionally skips a poll that repeats
  the last banked observation.

Data volume is tiny (a handful of open IPOs × a few polls/day), so — like
``ParquetRepository`` — the whole table is held in memory and rewritten on flush: the
simplest design that guarantees the append-only, idempotent contract. Rows are flat
scalars, so persistence is a plain ``model_dump``/``model_validate`` round-trip.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pyarrow as pa
import pyarrow.parquet as pq

from ipo.core.types import DaywiseSubscriptionRow

_DAYWISE_FILE = "daywise_subscription.parquet"


def _read_rows(path: Path) -> list[dict[str, Any]]:
    # pyarrow.parquet ships only partial type info; calls are untyped to mypy.
    table = pq.read_table(path)  # type: ignore[no-untyped-call]
    return cast(list[dict[str, Any]], table.to_pylist())


class DaywiseSubscriptionStore:
    """Append-only, idempotent Parquet bank of ``DaywiseSubscriptionRow``s.

    The natural key is ``(ipo_id, captured_at)``: appending a row whose key is already
    present is a no-op (immutable — the first observation stands). Rows are never mutated.
    """

    def __init__(self, data_dir: Path) -> None:
        """Open (or create) the bank under ``data_dir`` and load existing rows into memory."""
        self._dir = data_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = data_dir / _DAYWISE_FILE
        # Keyed by (ipo_id, captured_at ISO8601) for O(1) idempotency checks.
        self._rows: dict[tuple[str, str], DaywiseSubscriptionRow] = {}
        if self._path.is_file():
            for row in _read_rows(self._path):
                record = DaywiseSubscriptionRow.model_validate(row)
                self._rows[self._key(record)] = record

    @staticmethod
    def _key(row: DaywiseSubscriptionRow) -> tuple[str, str]:
        return (row.ipo_id, row.captured_at.isoformat())

    def append(self, row: DaywiseSubscriptionRow) -> bool:
        """Append one observation, unless its ``(ipo_id, captured_at)`` is already banked.

        Returns ``True`` if the row was newly banked, ``False`` if it was a duplicate key
        (never overwrites the existing row). Flushes on a real append.
        """
        key = self._key(row)
        if key in self._rows:
            return False  # append-only: an existing observation is immutable
        self._rows[key] = row
        self._flush()
        return True

    def append_many(self, rows: list[DaywiseSubscriptionRow]) -> int:
        """Append many observations with a single flush; returns how many were newly banked."""
        added = 0
        for row in rows:
            key = self._key(row)
            if key in self._rows:
                continue
            self._rows[key] = row
            added += 1
        if added:
            self._flush()
        return added

    def rows_for(self, ipo_id: str) -> list[DaywiseSubscriptionRow]:
        """Every banked poll for one IPO, in ``captured_at`` order (the reconstructed curve)."""
        rows = [r for r in self._rows.values() if r.ipo_id == ipo_id]
        rows.sort(key=lambda r: r.captured_at)
        return rows

    def latest_for(self, ipo_id: str) -> DaywiseSubscriptionRow | None:
        """The most-recently-captured banked poll for one IPO, or ``None`` if none exists."""
        rows = self.rows_for(ipo_id)
        return rows[-1] if rows else None

    def all_rows(self) -> list[DaywiseSubscriptionRow]:
        """Every banked row, ordered by ``(ipo_id, captured_at)`` for stable iteration."""
        rows = list(self._rows.values())
        rows.sort(key=lambda r: (r.ipo_id, r.captured_at))
        return rows

    def _flush(self) -> None:
        rows = [r.model_dump(mode="json") for r in self._rows.values()]
        if not rows:
            return
        pq.write_table(pa.Table.from_pylist(rows), self._path)  # type: ignore[no-untyped-call]
