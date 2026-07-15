"""VM-side pull-merge for the durable transitions archive (v3 V3-2) — thin CLI over the pull core.

Runs on the VM behind a systemd timer (the timer does ``git -C <clone> pull`` first; the merge is
kept git-free in :mod:`ipo.archive.pull` so it is unit-testable). Reads the dropped
``verdict_transitions.json`` from the rendezvous clone, REJECTS it whole if malformed/truncated
(exit 1, nothing merged — the archive's integrity never depends on the drop), else append-merges it
into the durable archive and mirrors the optional records snapshot. Idempotent: safe to run
repeatedly (a missed / doubled / out-of-order pull all converge to the same archive).

    python scripts/archive_pull.py --source <clone>/verdict_transitions.json --archive <archive-dir>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ipo.archive.pull import pull_merge
from ipo.archive.validate import ArchiveRejected
from ipo.core.logging import configure_logging, get_logger

_log = get_logger("ipo.archive.pull")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate + append-merge a transitions drop.")
    parser.add_argument("--source", required=True, help="the dropped verdict_transitions.json")
    parser.add_argument("--archive", required=True, help="the VM's durable archive directory")
    parser.add_argument(
        "--records", help="optional ipo_records.parquet snapshot to mirror alongside"
    )
    args = parser.parse_args()

    archive_dir = Path(args.archive)
    configure_logging("INFO", json_output=True, file_path=archive_dir / "logs" / "pull.log")

    source = Path(args.source)
    if not source.is_file():
        # Nothing dropped yet (dark-ship / first run before the app has pushed) — not an error.
        _log.warning("archive_pull_no_drop", extra={"source": str(source)})
        return
    try:
        added = pull_merge(source, archive_dir, Path(args.records) if args.records else None)
    except ArchiveRejected as exc:
        # Loud: a malformed/truncated drop is NEVER merged. The archive is left exactly as it was.
        _log.error("archive_pull_rejected", extra={"error": str(exc)})
        sys.exit(1)
    _log.info("archive_pull_merged", extra={"added": added})


if __name__ == "__main__":
    main()
