"""Record hygiene: merge partials, tag segment, flag bad records (Deep Dive #1).

Several sources each contribute a ``PartialRecord``; this layer reconciles them into
one canonical ``IPORecord``. The trust policy (Deep Dive #1) is enforced here:
label/backtest-critical fields are cross-checked across sources, and a disagreement
between an official source and an aggregator is logged as a conflict rather than
silently accepted. Records that fail validation (or miss a critical field) are sent
to the bad-record log and excluded — never half-built.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from pydantic import ValidationError

from ipo.core.constants import SEGMENT_MAINBOARD, SEGMENT_SME
from ipo.core.logging import get_logger
from ipo.core.types import IPORecord, PartialRecord, Segment

_log = get_logger("ipo.data.hygiene")

# Relative tolerance for cross-checking numeric fields between sources.
_NUMERIC_TOLERANCE = 0.01

_RECORD_FIELDS = frozenset(IPORecord.model_fields)


@dataclass
class MergeResult:
    """The merged field map plus any cross-source conflicts detected."""

    fields: dict[str, object]
    conflicts: list[str] = field(default_factory=list)


@dataclass
class BadRecordLog:
    """Accumulates records that could not be built, with the reason (logged, excluded)."""

    entries: list[tuple[str, str]] = field(default_factory=list)

    def add(self, ipo_id: str, reason: str) -> None:
        """Record and log one bad record."""
        self.entries.append((ipo_id, reason))
        _log.warning("bad_record", extra={"ipo_id": ipo_id, "reason": reason})

    def __len__(self) -> int:
        """Return the number of bad records logged."""
        return len(self.entries)


def normalize_segment(value: object) -> Segment:
    """Coerce a raw segment value to the ``Segment`` enum; raise on anything else."""
    text = str(value).strip().lower()
    if text in {SEGMENT_MAINBOARD, "mainline"}:
        return Segment.MAINBOARD
    if text == SEGMENT_SME:
        return Segment.SME
    raise ValueError(f"unrecognized segment: {value!r}")


def _values_match(a: object, b: object) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if a == 0:
            return abs(b) < _NUMERIC_TOLERANCE
        return math.isclose(float(a), float(b), rel_tol=_NUMERIC_TOLERANCE)
    return a == b


def merge_partials(
    partials: list[PartialRecord],
    *,
    cross_check_fields: frozenset[str],
    source_priority: list[str],
) -> MergeResult:
    """Merge partials in source-priority order, cross-checking critical fields.

    Higher-priority (more authoritative) sources win. When a lower-priority source
    disagrees on a ``cross_check_fields`` value, the disagreement is recorded as a
    conflict (the authoritative value is kept).
    """

    def rank(name: str) -> int:
        return source_priority.index(name) if name in source_priority else len(source_priority)

    ordered = sorted(partials, key=lambda p: rank(p.source))
    merged: dict[str, object] = {}
    provenance: dict[str, str] = {}
    conflicts: list[str] = []

    for partial in ordered:
        for key, value in partial.fields.items():
            if value is None:
                continue
            if key not in merged:
                merged[key] = value
                provenance[key] = partial.source
            elif key in cross_check_fields and not _values_match(merged[key], value):
                conflicts.append(
                    f"{key}: {provenance[key]}={merged[key]!r} vs {partial.source}={value!r}"
                )
                # Name each disagreement, not just the count — a cross-source conflict on a
                # backtest-critical field is a data-quality event worth seeing individually.
                _log.warning(
                    "source_conflict",
                    extra={
                        "field": key,
                        "kept_source": provenance[key],
                        "kept_value": merged[key],
                        "other_source": partial.source,
                        "other_value": value,
                    },
                )
    return MergeResult(fields=merged, conflicts=conflicts)


def build_record(
    ipo_id: str,
    fields: dict[str, object],
    *,
    source_hashes: dict[str, str],
) -> IPORecord:
    """Build a validated ``IPORecord`` from merged fields (raises on invalid data).

    Only known record fields are passed through; extra source-specific keys (e.g.
    an aggregator's ``listing_gain_pct``) are dropped. ``captured_at`` is stamped now.
    """
    from ipo.core.calendar import now_ist

    payload: dict[str, object] = {k: v for k, v in fields.items() if k in _RECORD_FIELDS}
    payload["ipo_id"] = ipo_id
    if "segment" in payload:
        payload["segment"] = normalize_segment(payload["segment"])
    payload["captured_at"] = now_ist()
    payload["source_hashes"] = source_hashes
    return IPORecord.model_validate(payload)


def is_mainboard(record: IPORecord) -> bool:
    """True if the record is a mainboard issue (SME is excluded/penalized upstream)."""
    return record.segment is Segment.MAINBOARD


def try_build_record(
    ipo_id: str,
    fields: dict[str, object],
    *,
    source_hashes: dict[str, str],
    bad_records: BadRecordLog,
) -> IPORecord | None:
    """Build a record, routing any validation failure to the bad-record log."""
    try:
        return build_record(ipo_id, fields, source_hashes=source_hashes)
    except (ValidationError, ValueError) as exc:
        bad_records.add(ipo_id, str(exc).replace("\n", " ")[:300])
        return None
