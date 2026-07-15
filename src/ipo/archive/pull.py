"""Validate + append-merge a transitions drop into the durable archive (v3 V3-2) — the pull core.

Git-free (the systemd timer does the ``git pull``; this is the pure validate+merge that
``scripts/archive_pull.py`` wraps as a CLI) so it is fully unit-testable, and idempotent by
construction (the merge is a union — a missed / doubled / out-of-order pull all converge).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ipo.archive.merge import merge_transitions
from ipo.archive.store import read_archive, write_archive
from ipo.archive.validate import load_validated

ARCHIVE_NAME = "verdict_transitions.json"


def pull_merge(source: Path, archive_dir: Path, records: Path | None = None) -> int:
    """Validate the drop at ``source`` and append-merge into ``archive_dir``. Returns rows added.

    Raises ``ArchiveRejected`` (from :func:`ipo.archive.validate.load_validated`, before the archive
    is read or written) if the drop is malformed/truncated — so a rejected drop leaves the archive
    EXACTLY as it was. The records snapshot (reproducible-not-necessary) is a latest-wins mirror.
    """
    incoming = load_validated(
        source.read_text(encoding="utf-8-sig")
    )  # -sig tolerates a leading BOM
    archive_file = archive_dir / ARCHIVE_NAME
    before = read_archive(archive_file)
    merged = merge_transitions(before, incoming)
    write_archive(archive_file, merged)
    if records and records.is_file():
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(records, archive_dir / records.name)
    return len(merged) - len(before)
