"""The append-only subscription series store (v3-DP DP-1).

PHYSICAL SHAPE FOLLOWS THE DURABILITY DECISION, not the other way round — the blueprint left the
layout deliberately open so an engineering-safety choice would not be constrained by a
documentation one.

The load-bearing fact is that **each IPO's series is BOUNDED**: the open->close window is ~3 days,
so at one sample per 30-min cycle a completed series is ~150 samples / ~150 KB. It *completes*
rather than growing forever. That kills the usual objection to rewriting a file on every append,
and makes the strongest option also the cheapest:

    ONE FILE PER IPO, replaced atomically via tmp + os.replace.

Why this and not the alternatives:

* **Single Parquet, full rewrite** (what the retired v2-A1 recorder did) — REJECTED. Its ``_flush``
  called ``pq.write_table`` straight onto the live path, so a crash mid-write truncates the ENTIRE
  accumulated bank. That is precisely the torn-parquet corruption the code review raised as its
  #2/#3 criticals, and this store is nothing but appends running unattended for months.
* **Single file, atomic rewrite** — REJECTED. Atomic, but rewrites every IPO's whole history every
  cycle and holds the entire bank in memory.
* **Append-native JSONL** — REJECTED. A sample carries the full ~4.4 KB NSE response, which is over
  ``PIPE_BUF``, so a single-line append is NOT atomic. That introduces a torn-line class we would
  then have to detect on every read.
* **SQLite** — a genuine contender (stdlib, ACID), but it adds a second storage technology and a
  corrupt database is far worse to recover by hand than a readable JSON file.

With ``os.replace`` a partially-written file can never appear at the live path: the previous
complete file is intact until the instant the new one atomically supplants it. There is no torn
state to detect, which is a stronger guarantee than being able to detect one. Blast radius is one
IPO. This also reuses the ONE atomic-write pattern already established in this codebase
(``data/ingest/state.py::IngestStateStore._flush``, replicated for the context cache in
``data/ingest/data_plane.py``).

Append-only is ENFORCED, not assumed. A full rewrite could in principle truncate through a bug, so
every write must satisfy two invariants or it is refused outright:

    1. NEVER-OVERWRITE — an existing ``(ipo_id, captured_at)`` observation is immutable.
    2. NEVER-SHRINK    — the outgoing sample list may not be shorter than the one on disk.

B1 WALL: see ``ipo/series/__init__.py``. This store is read by a display route (DP-2) and an
offline study (DP-4); it is read by the model NEVER, and the import-boundary test makes that
structural rather than conventional.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from pydantic import ValidationError

from ipo.series.models import SubscriptionSample

_log = logging.getLogger(__name__)

_SERIES_DIR = "series"
# ipo_id reaches us from NSE's symbol (lower-cased). Anything outside this set could escape the
# series directory via the filename, so it is refused rather than sanitised — sanitising two
# different ids into one filename would silently merge two IPOs' series.
_SAFE_IPO_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class SeriesWriteError(RuntimeError):
    """A write was REFUSED to protect already-banked data. Never raised past the recorder."""


class SubscriptionSeriesStore:
    """One writer, one home. Reads by ``ipo_id``; DP-2 depends on that, never on the layout."""

    def __init__(self, data_dir: Path) -> None:
        """Open (creating if needed) the series directory under ``data_dir``."""
        self._dir = data_dir / _SERIES_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def directory(self) -> Path:
        """The series directory itself (one file per IPO)."""
        return self._dir

    def path_for(self, ipo_id: str) -> Path:
        """The on-disk path for one IPO's series. Refuses an id unsafe as a filename."""
        if not _SAFE_IPO_ID.match(ipo_id):
            raise SeriesWriteError(f"unsafe ipo_id for a filename: {ipo_id!r}")
        return self._dir / f"{ipo_id}.json"

    # --- reading -----------------------------------------------------------

    def read(self, ipo_id: str) -> list[SubscriptionSample]:
        """Every banked sample for one IPO, oldest first. Honest-empty on absent OR corrupt.

        Degrading to empty (plus a loud log) rather than raising is what DP-2's read route needs:
        for months, MOST IPOs will legitimately have no series, and that must read as "not
        recorded" rather than as a failure. A corrupt file must not 500 the box either.
        Writers use ``_read_for_write`` instead, which refuses to proceed on corruption.
        """
        try:
            return self._load(self.path_for(ipo_id))
        except FileNotFoundError:
            return []
        except (OSError, ValueError, ValidationError, SeriesWriteError) as exc:
            _log.warning("series_read_failed", extra={"ipo_id": ipo_id, "error": str(exc)})
            return []

    def recorded_ipo_ids(self) -> list[str]:
        """Every ipo_id with a series on disk (sorted). Cheap — a directory listing."""
        return sorted(p.stem for p in self._dir.glob("*.json"))

    def _load(self, path: Path) -> list[SubscriptionSample]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"series file is not a list: {path.name}")
        return [SubscriptionSample.model_validate(row) for row in payload]

    def _read_for_write(self, path: Path) -> list[SubscriptionSample]:
        """Strict read used before a write — corruption REFUSES the write, never overwrites it.

        If an existing file cannot be parsed we must not "start fresh": that would replace an
        unreadable-but-present series with a one-row file, destroying months of banked data to
        recover from what may be a transient read error. Refusing keeps the bytes on disk for
        manual recovery, and the failure surfaces on the health row.
        """
        if not path.is_file():
            return []
        try:
            return self._load(path)
        except (OSError, ValueError, ValidationError) as exc:
            raise SeriesWriteError(
                f"refusing to write {path.name}: existing series is unreadable ({exc}) — "
                "the banked data is left untouched for recovery"
            ) from exc

    # --- writing -----------------------------------------------------------

    def append_many(self, ipo_id: str, samples: list[SubscriptionSample]) -> int:
        """Append new observations for ONE IPO. Returns how many were newly banked.

        Idempotent: re-appending an already-banked ``(ipo_id, captured_at)`` is a no-op, so a
        re-run (or a manual off-schedule fetch landing beside an auto one) converges rather than
        duplicating. Raises ``SeriesWriteError`` if either append-only invariant would be broken.
        """
        if not samples:
            return 0
        wrong = [s.ipo_id for s in samples if s.ipo_id != ipo_id]
        if wrong:
            raise SeriesWriteError(f"sample ipo_id mismatch for {ipo_id!r}: {sorted(set(wrong))}")

        path = self.path_for(ipo_id)
        existing = self._read_for_write(path)
        by_key = {s.key: s for s in existing}
        before = len(by_key)

        added = 0
        for sample in samples:
            if sample.key in by_key:
                continue  # NEVER-OVERWRITE: an observation at an instant is immutable
            by_key[sample.key] = sample
            added += 1
        if added == 0:
            return 0

        merged = self._merge(by_key)
        # NEVER-SHRINK, checked against what is actually on disk and BEFORE the write, so a
        # violation writes nothing at all. `_merge` is a separate seam precisely so this is a real
        # check rather than a comment: today it only sorts, but the day someone adds pruning,
        # retention or filtering there, this catches it instead of silently eating a months-old
        # series. That seam is what makes the guard testable, and it is tested.
        if len(merged) < before:
            raise SeriesWriteError(
                f"refusing to shrink {path.name}: {before} banked samples -> {len(merged)}"
            )
        self._atomic_write(path, merged)
        return added

    def _merge(self, by_key: dict[tuple[str, str], SubscriptionSample]) -> list[SubscriptionSample]:
        """The full outgoing series, oldest first. MUST NOT drop samples — see NEVER-SHRINK."""
        return sorted(by_key.values(), key=lambda s: s.captured_at)

    def _atomic_write(self, path: Path, samples: list[SubscriptionSample]) -> None:
        """Write via tmp + ``os.replace`` — the one pattern for a store a reader may read live.

        A crash before ``os.replace`` leaves the previous COMPLETE file in place; a crash after it
        leaves the new complete file. No interleaving is observable at ``path``, so an interrupted
        write can never corrupt or truncate the accumulated series.
        """
        body = json.dumps([s.model_dump(mode="json") for s in samples], ensure_ascii=False)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)
