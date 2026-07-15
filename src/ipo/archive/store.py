"""Read / atomic-write the durable transitions archive file (v3 V3-2).

Kept in the SAME JSON-array shape as the app's ``verdict_transitions.json`` so recovery is a plain
copy-back. Written atomically (tmp + ``os.replace``) so a crash mid-write can never truncate the
archive it exists to protect. A corrupt existing archive raises (via the validator) rather than
being silently reset — losing durable history to a silent reset would defeat the whole point.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ipo.archive.validate import load_validated
from ipo.service.transitions import VerdictTransition


def read_archive(path: Path) -> list[VerdictTransition]:
    """Load the archive (``[]`` if absent). Corrupt content raises ``ArchiveRejected``."""
    if not path.is_file():
        return []
    return load_validated(path.read_text(encoding="utf-8-sig"))  # -sig tolerates a leading BOM


def write_archive(path: Path, transitions: list[VerdictTransition]) -> None:
    """Atomically write the archive as a JSON array (tmp + ``os.replace`` — never a torn file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [t.model_dump(mode="json") for t in transitions]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # atomic swap so a concurrent reader / a crash never sees a partial file
