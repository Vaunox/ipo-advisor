"""Recorder health state (v3-DP DP-1) — so the recorder cannot die silently.

Silent failure is the cardinal risk for this whole workstream: DP-1's payoff is deferred by months,
so a recorder that stops writing looks *exactly* like a recorder with nothing to write, right up
until the day you need the data and find a hole. This file is what makes those two states
distinguishable.

The distinction that matters, and the reason this holds more than a timestamp:

    NO IPO IN THE WINDOW  -> writing nothing is CORRECT. Between IPOs that is the normal state for
                             days or weeks at a time, and a health row that goes red for it would
                             cry wolf until it was ignored — which is how a real failure gets
                             missed.
    IPO IN THE WINDOW, NO WRITE -> genuinely broken, and must be loud.

So each cycle records not just "did I write" but "was there anything to write" (``in_window``) and
"did I run at all" (``last_cycle_at``). A stalled *cycle* is caught by ``last_cycle_at`` ageing out
even when ``in_window`` is legitimately zero — otherwise a recorder that stopped running entirely
would look identical to a quiet week.

Single writer: the DP-1 recorder, on the VM, inside the ``ipo-ingest.service`` cycle.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

_log = logging.getLogger(__name__)

_STATE_FILE = "recorder_state.json"


class RecorderState(BaseModel):
    """What the last recorder cycle did.

    Every field is optional-with-default, so an older file on disk still validates — a breaking
    change here would read as "recorder dead" and cry wolf.
    """

    model_config = ConfigDict(extra="ignore")

    last_cycle_at: datetime | None = None
    last_write_at: datetime | None = None
    samples_last_cycle: int = 0
    samples_total: int = 0
    in_window_last_cycle: int = 0
    last_error: str | None = None


class RecorderStateStore:
    """Reads/writes ``recorder_state.json`` with the same atomic pattern as the series itself."""

    def __init__(self, data_dir: Path) -> None:
        """Open (creating if needed) the series directory holding the recorder state file."""
        self._path = data_dir / "series" / _STATE_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        """Where the recorder state is persisted."""
        return self._path

    def read(self) -> RecorderState:
        """Last-known state; a missing or corrupt file degrades to an empty state, never raises.

        An empty state reads as "never run", which is the honest answer when the file is gone.
        """
        if not self._path.is_file():
            return RecorderState()
        try:
            return RecorderState.model_validate_json(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError) as exc:
            _log.warning("recorder_state_load_failed", extra={"error": str(exc)})
            return RecorderState()

    def record_cycle(
        self,
        *,
        now: datetime,
        in_window: int,
        written: int,
        error: str | None = None,
    ) -> RecorderState:
        """Fold one cycle's outcome into the state and persist it atomically."""
        prior = self.read()
        state = RecorderState(
            last_cycle_at=now,
            # Only a real write advances last_write_at — a quiet cycle must not look like a write.
            last_write_at=now if written else prior.last_write_at,
            samples_last_cycle=written,
            samples_total=prior.samples_total + written,
            in_window_last_cycle=in_window,
            last_error=error,
        )
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, self._path)
        return state


def read_recorder_state(data_dir: Path) -> RecorderState:
    """Convenience read for the health surface (which must not construct a writer)."""
    return RecorderStateStore(data_dir).read()


__all__ = ["RecorderState", "RecorderStateStore", "read_recorder_state"]
