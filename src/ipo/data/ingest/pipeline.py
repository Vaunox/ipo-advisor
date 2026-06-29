"""Ingestion orchestrator: sources -> merge -> hygiene -> store + labels.

Ties Layer 1 together into a reproducible, incremental pull. For each ``ipo_id`` it
gathers a ``PartialRecord`` from every source (a single source's failure degrades
that field, it does not crash the run), merges them under the trust policy, builds a
validated ``IPORecord`` (routing failures to the bad-record log), upserts to the
repository, and rebuilds the listing-label table from the full store.

Re-running is idempotent (keyed on ``ipo_id``); passing a subset of ids performs an
incremental update.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ipo.core.interfaces import DataSource, Repository
from ipo.core.logging import get_logger
from ipo.data.hygiene.clean import BadRecordLog, merge_partials, try_build_record
from ipo.data.labels.builder import build_labels
from ipo.data.sources.base import SourceError

_log = get_logger("ipo.data.ingest")


@dataclass
class IngestReport:
    """Summary of one ingest run (logged; returned for tests and the CLI)."""

    records_ingested: int = 0
    labels_built: int = 0
    bad_records: list[tuple[str, str]] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    per_source: dict[str, int] = field(default_factory=dict)


class IngestPipeline:
    """Runs the Layer-1 pull across a set of sources into a repository."""

    def __init__(
        self,
        sources: Sequence[DataSource],
        repo: Repository,
        *,
        cross_check_fields: frozenset[str],
        source_priority: list[str],
    ) -> None:
        """Wire sources and the repository with the cross-check trust policy."""
        if not sources:
            raise ValueError("at least one source is required")
        self._sources = list(sources)
        self._repo = repo
        self._cross_check_fields = cross_check_fields
        self._source_priority = source_priority

    def run(self, ipo_ids: Sequence[str]) -> IngestReport:
        """Ingest the given ids, upsert records, rebuild labels, and return a report."""
        report = IngestReport(per_source={s.name: 0 for s in self._sources})
        bad = BadRecordLog()
        built = []

        for ipo_id in ipo_ids:
            partials = []
            source_hashes: dict[str, str] = {}
            for source in self._sources:
                try:
                    raw = source.fetch(ipo_id)
                    partials.append(source.parse(raw))
                    source_hashes[source.name] = raw.content_hash
                    report.per_source[source.name] += 1
                except SourceError as exc:
                    _log.warning(
                        "source_degraded",
                        extra={"source": source.name, "ipo_id": ipo_id, "error": str(exc)},
                    )

            if not partials:
                bad.add(ipo_id, "no source produced a usable record")
                continue

            merged = merge_partials(
                partials,
                cross_check_fields=self._cross_check_fields,
                source_priority=self._source_priority,
            )
            report.conflicts.extend(merged.conflicts)

            record = try_build_record(
                ipo_id, merged.fields, source_hashes=source_hashes, bad_records=bad
            )
            if record is not None:
                built.append(record)

        self._repo.upsert_many(built)
        all_records = self._repo.list_all()
        labels = build_labels(all_records)
        self._repo.save_labels(labels)

        report.records_ingested = len(built)
        report.labels_built = len(labels)
        report.bad_records = bad.entries
        _log.info(
            "ingest_complete",
            extra={
                "records_ingested": report.records_ingested,
                "labels_built": report.labels_built,
                "bad_records": len(report.bad_records),
                "conflicts": len(report.conflicts),
            },
        )
        return report
