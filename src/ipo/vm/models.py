"""Shared envelope schemas for the VM data plane (v3 V3-1).

The read-API SERVER (``vm.server``) produces these and the app-side CLIENT (``vm.client``) validates
against them — one schema, both ends, so "don't trust a 200" is enforced by parsing, not by hope. A
malformed or truncated response fails to parse → the client treats the VM as unavailable and falls
back to local, rather than feeding garbage into the app.

* ``RecordsEnvelope`` is validated **deeply** (every ``IPORecord``): these feed the local scorer, so
  a bad shape must never reach it.
* ``ContextEnvelope`` is validated at the **envelope** level only (``ipos`` left as raw objects):
  context is display-only and walled from the model, and ``ContextStore`` re-validates it on read,
  so the client only needs to confirm it is a well-formed ``{refreshed_at, ipos}`` document.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from ipo.core.types import IPORecord


class RecordsEnvelope(BaseModel):
    """The NSE record store + its freshness (the last confirmed-good ingest)."""

    refreshed_at: datetime | None = None
    records: list[IPORecord]


class ContextEnvelope(BaseModel):
    """The Upstox context cache, exactly as the cache file stores it ({refreshed_at, ipos})."""

    refreshed_at: datetime | None = None
    ipos: dict[str, Any] = {}
