"""Read the engine log for the debug console (V3-16) — READ-ONLY, no second logging path.

The console consumes the log the engine already writes; it never creates its own. Two sources, both
**already redacted at write time** (``core.logging.redacted_payload`` — token/PAN/auth-header can
never appear): the in-memory **ring buffer** (recent live tail, each entry carrying a monotonic
``seq`` for cheap incremental polling) and the **rotated files** on disk (durable scroll-back
history). This module only reads them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ipo.core.logging import get_ring_buffer

# Newest-last on disk: engine.log is current, engine.log.1 the previous rotation, … .4 the oldest.
_ROTATED = ("engine.log.4", "engine.log.3", "engine.log.2", "engine.log.1", "engine.log")

_MAX_LIMIT = 5000


def clamp_limit(limit: int, *, default: int = 500) -> int:
    """Clamp a client-supplied limit into ``[1, _MAX_LIMIT]`` (bounds the response size)."""
    if limit <= 0:
        return default
    return min(limit, _MAX_LIMIT)


def ring_tail(*, since: int, limit: int) -> tuple[list[dict[str, Any]], int]:
    """Recent ring-buffer entries with ``seq > since`` (newest ``limit``) + the latest seq cursor.

    ``([], 0)`` when the ring is not configured (e.g. a batch process) — the console degrades to an
    empty tail rather than erroring.
    """
    ring = get_ring_buffer()
    if ring is None:
        return [], 0
    return ring.entries(since=since, limit=limit), ring.latest_seq()


def file_history(log_dir: Path, *, limit: int, before: str | None = None) -> list[dict[str, Any]]:
    """The newest ``limit`` parsed JSON log lines from the rotated files (oldest→newest).

    Durable scroll-back history for the console's one continuous timeline. When ``before`` (an ISO
    ``ts``) is given, only entries with ``ts <= before`` are returned — the cursor the front end
    pages backward with as it scrolls up, so it loads older chunks lazily instead of the whole file.
    (``<=`` is deliberate: the boundary line overlaps the caller's oldest, which the client
    de-dupes, so the ring→disk seam has no gap.) ISO timestamps share one IST offset, so a
    lexicographic string compare is chronological. Reads newest→oldest only until it has ``limit``
    lines, skipping any unparseable/blank line rather than failing the read.
    """
    collected: list[dict[str, Any]] = []
    for name in reversed(_ROTATED):  # newest file first
        path = log_dir / name
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in reversed(lines):  # newest line first within the file
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue  # a torn line mid-rotation — skip, don't fail the read
            if not isinstance(obj, dict):
                continue
            if before is not None and str(obj.get("ts", "")) > before:
                continue  # newer than the scroll cursor — not part of this older page
            collected.append(obj)
            if len(collected) >= limit:
                break
        if len(collected) >= limit:
            break
    collected.reverse()  # newest-first while gathering → back to chronological (oldest→newest)
    return collected
