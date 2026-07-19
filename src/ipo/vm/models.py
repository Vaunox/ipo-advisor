"""Shared envelope schemas for the VM data plane (v3 V3-1).

The read-API SERVER (``vm.server``) produces these and the app-side CLIENT (``vm.client``) validates
against them — one schema, both ends, so "don't trust a 200" is enforced by parsing, not by hope. A
malformed or truncated response fails to parse → the client treats the VM as unavailable and falls
back to local, rather than feeding garbage into the app.

* ``RecordsEnvelope`` is validated **deeply** (every ``IPORecord``): these feed the local scorer, so
  a bad shape must never reach it.
* ``ContextEnvelope`` is validated at the **envelope** level only (``ipos`` left as raw objects):
  context is display-only and walled from the model, and ``ContextStore`` re-validates each entry
  when it (re-)reads the cache file, so the client only needs to confirm it is a well-formed
  ``{refreshed_at, ipos}`` document. *(Accurate as of BUG-4: before that fix ``ContextStore``
  validated once at construction and never re-read, so this sentence described behaviour the code
  did not have. The two now agree.)*
* ``SeriesEnvelope`` (v3-DP DP-2) is validated **deeply** (every ``SeriesSample``) — not because it
  feeds the scorer (it must never; see the B1 wall) but because DP-3 plots it, and a chart fed a
  malformed reading would draw a confident wrong line. Deep validation is cheap here because the
  samples are a small typed projection, not the raw store rows.
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


class SeriesSample(BaseModel):
    """One point on an IPO's subscription curve — the WIRE projection, not the stored row.

    DELIBERATELY LEANER THAN THE STORE ROW, and this is DP-2's one real design decision. DP-1 banks
    the complete NSE response plus every category row, because a field discarded at collection time
    can never be recovered. Serving all of that is a different question: measured against the first
    real banked sample, a stored row is **6,163 bytes**, so a full ~150-sample trajectory would be
    **~903 KB per request** — handed to a 1 vCPU / 1 GB box on every detail-page open. This
    projection is **376 bytes** a sample, ~55 KB for the same trajectory.

    Scoping the route to one IPO does not solve this on its own; the per-IPO payload was itself the
    problem. What DP-3 draws is the multiples over time, so that is what crosses the wire.
    ``raw_response`` and ``categories`` stay on disk for DP-4, which reads the store directly on the
    VM rather than over HTTP — no data is lost, only un-shipped.
    """

    schema_version: int
    captured_at: datetime
    # NSE's own "when this reading was true" stamp, verbatim. Kept because it is what distinguishes
    # a genuine flat stretch from a stalled feed — visible on the very first live sample, where a
    # weekend capture correctly carried a two-day-old book.
    source_update_time: str | None = None
    qib_sub: float | None = None
    nii_sub: float | None = None
    snii_sub: float | None = None
    bnii_sub: float | None = None
    retail_sub: float | None = None
    total_sub: float | None = None


class SeriesEnvelope(BaseModel):
    """One IPO's banked subscription trajectory + its OWN freshness (v3-DP DP-2).

    ``refreshed_at`` is **per-IPO** — the most recent reading banked for THIS ipo_id — not the
    app-global ``last_success`` that ``/records`` carries. A per-IPO series has per-IPO freshness:
    one IPO may be open and still growing while another closed last week and is complete. DP-3 must
    read this timestamp rather than the global clock, which would misreport a finished curve as
    stale.

    ``samples`` is ordered oldest-first. An empty list is a NORMAL, honest answer — for months most
    IPOs will have no series at all — and is never an error.
    """

    refreshed_at: datetime | None = None
    ipo_id: str
    samples: list[SeriesSample] = []
