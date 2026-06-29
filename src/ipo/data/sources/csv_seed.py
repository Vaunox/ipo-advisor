"""CSV seed source — the deterministic, fully-tested ingestion path.

A curated CSV of past mainboard IPOs is a legitimate ``DataSource``: it is how the
operator assembles and grows the >=100-IPO calibration sample (and the path the
backtest reads) without depending on fragile live scraping. Each row carries the
full field set; ``fetch`` serializes one row into a hashed ``RawResponse`` and
``parse`` validates it into a ``PartialRecord``.

Schema-validate on parse -> fail loud (Deep Dive #1, Module 3): a missing required
column or an off-type value raises ``SourceError`` rather than yielding a
half-record.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from ipo.core.calendar import now_ist
from ipo.core.types import PartialRecord, RawResponse
from ipo.data.sources.base import SourceError, compute_hash

SOURCE_NAME = "csv_seed"

# Columns every seed row must provide (header presence is the schema contract).
_REQUIRED_COLUMNS = (
    "ipo_id",
    "name",
    "segment",
    "price_band_low",
    "price_band_high",
    "open_date",
    "close_date",
)
# Typed coercion for each column. Absent/blank optional fields become ``None``.
_FLOAT_FIELDS = (
    "price_band_low",
    "price_band_high",
    "issue_size_cr",
    "ofs_fraction",
    "qib_sub",
    "nii_sub",
    "retail_sub",
    "issue_pe",
    "peer_median_pe",
    "listing_open",
    "listing_close",
)
_INT_FIELDS = ("lot_size",)
_BOOL_FIELDS = ("promoter_litigation",)
_DATE_FIELDS = ("open_date", "close_date", "listing_date")
_STR_FIELDS = ("ipo_id", "name", "segment")


def _coerce(column: str, value: str) -> object:
    """Coerce one raw CSV cell to its typed value; blank -> ``None`` for optionals."""
    text = value.strip()
    if column in _STR_FIELDS:
        return text
    if text == "":
        return None
    if column in _FLOAT_FIELDS:
        return float(text)
    if column in _INT_FIELDS:
        return int(text)
    if column in _BOOL_FIELDS:
        return text.lower() in {"1", "true", "yes"}
    if column in _DATE_FIELDS:
        return text  # ISO string; record builder parses to date
    return text


class CsvSeedSource:
    """A ``DataSource`` backed by a curated CSV of historical IPOs."""

    name = SOURCE_NAME

    def __init__(self, csv_path: Path) -> None:
        """Load and index the seed CSV by ``ipo_id`` (fails loud on a bad header/dupe)."""
        self._path = csv_path
        self._rows: dict[str, dict[str, str]] = {}
        if not csv_path.is_file():
            raise SourceError(f"seed CSV not found: {csv_path}")
        with csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            header = reader.fieldnames or []
            missing = [c for c in _REQUIRED_COLUMNS if c not in header]
            if missing:
                raise SourceError(f"seed CSV missing required columns: {missing}")
            for row in reader:
                ipo_id = (row.get("ipo_id") or "").strip()
                if not ipo_id:
                    raise SourceError("seed CSV row has empty ipo_id")
                if ipo_id in self._rows:
                    raise SourceError(f"seed CSV has duplicate ipo_id: {ipo_id}")
                self._rows[ipo_id] = row

    def ipo_ids(self) -> list[str]:
        """Return every ``ipo_id`` available in the seed (enumeration for a full pull)."""
        return list(self._rows)

    def fetch(self, ipo_id: str) -> RawResponse:
        """Return the seed row for ``ipo_id`` as a hashed raw response."""
        row = self._rows.get(ipo_id)
        if row is None:
            raise SourceError(f"{self.name}: unknown ipo_id {ipo_id}")
        content = json.dumps(row, sort_keys=True)
        return RawResponse(
            source=self.name,
            url=f"file://{self._path}#{ipo_id}",
            fetched_at=now_ist(),
            content=content,
            content_hash=compute_hash(content),
        )

    def parse(self, raw: RawResponse) -> PartialRecord:
        """Validate and coerce a seed raw into a ``PartialRecord`` (pure)."""
        try:
            row: dict[str, str] = json.loads(raw.content)
        except json.JSONDecodeError as exc:
            raise SourceError(f"{self.name}: malformed raw content") from exc

        missing = [c for c in _REQUIRED_COLUMNS if c not in row or row[c].strip() == ""]
        if missing:
            raise SourceError(f"{self.name}: row missing required fields: {missing}")

        fields: dict[str, object] = {}
        for column, value in row.items():
            try:
                fields[column] = _coerce(column, value)
            except ValueError as exc:
                raise SourceError(f"{self.name}: bad value for {column}={value!r}") from exc
        return PartialRecord(source=self.name, ipo_id=str(fields["ipo_id"]), fields=fields)
