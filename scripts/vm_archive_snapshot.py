"""VM-side durable-archive snapshot push (v3 V3-2 revised): mirror app data to ``ipo-archive``.

Runs on the VM behind a systemd timer (daily). Copies the two app-facing data files — the records
store and the context cache — into the ``ipo-archive`` git clone; the systemd unit's own git step
then commits (only if something actually changed) and pushes with the archive's write-scoped deploy
key. Kept git-free here, same as the old pull-merge script, so the copy itself stays unit-testable:
the git add/diff/commit/push sequence lives in the unit file's shell step, not in this module.

Replaces the old pull-merge role (``archive_pull.py``, retired): with the desktop drop gone,
``ipo-archive`` is now a VM-write, single-writer durable copy — not a place anything drops into.

    python scripts/vm_archive_snapshot.py --data-dir <vm-data> --archive-clone <ipo-archive-clone>
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from ipo.core.logging import configure_logging, get_logger

_log = get_logger("ipo.service.vm_archive_snapshot")

RECORDS_FILENAME = "ipo_records.parquet"
CONTEXT_FILENAME = "ipo_context.json"


def _copy_if_present(source: Path, dest: Path) -> bool:
    """Copy ``source`` to ``dest`` if it exists. Returns whether a copy happened."""
    if not source.is_file():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    shutil.copyfile(source, tmp)
    tmp.replace(dest)  # atomic on the same filesystem — no reader ever sees a partial file
    return True


def sync_snapshot(data_dir: Path, archive_dir: Path) -> list[str]:
    """Mirror the records store + context cache into the archive clone. Returns files copied.

    A source that is expected but ABSENT is logged (WARN) rather than silently omitted, so an empty
    snapshot (e.g. the records store was never written) is loud instead of an innocent-looking
    ``copied=[]`` that reads like a healthy no-change sync.
    """
    archive_dir.mkdir(parents=True, exist_ok=True)
    sources = {
        RECORDS_FILENAME: data_dir / RECORDS_FILENAME,
        CONTEXT_FILENAME: data_dir / "context" / CONTEXT_FILENAME,
    }
    copied: list[str] = []
    missing: list[str] = []
    for name, src in sources.items():
        if _copy_if_present(src, archive_dir / name):
            copied.append(name)
        else:
            missing.append(name)
    if missing:
        _log.warning("archive_snapshot_source_missing", extra={"missing": missing})
    return copied


def main() -> None:
    parser = argparse.ArgumentParser(description="Mirror records + context into ipo-archive.")
    parser.add_argument("--data-dir", required=True, help="the VM data dir (records, context/)")
    parser.add_argument("--archive-clone", required=True, help="the ipo-archive git clone")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    log_path = data_dir / "logs" / "archive_snapshot.log"
    configure_logging("INFO", json_output=True, file_path=log_path)
    copied = sync_snapshot(data_dir, Path(args.archive_clone))
    _log.info("archive_snapshot_synced", extra={"copied": copied})


if __name__ == "__main__":
    main()
