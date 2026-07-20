"""VM read-API — the READ plane of the data layer (v3 V3-1c).

The VM serves every store the app reads over ONE small GET-only HTTP API: the NSE record store and
the Upstox context cache, each in a ``{refreshed_at, data}`` envelope so freshness travels *with*
the data (the app applies one staleness rule to whichever path served it).

Two guarantees are structural, not careful:

* **Read-only.** GET only — there is no mutation route anywhere in this module. The app reads from
  the VM; it can NEVER make the VM act (the door refused for BUG 1 and re-refused in V3-1). The
  write/backup direction (app history → VM archive) is deliberately NOT here: it is a separate,
  non-network-facing mechanism (the VM pulls — see V3-2), so a bug or a compromised app can never
  corrupt the durable archive it is meant to protect.
* **No model.** It serves *inputs* (records + context); the app scores LOCALLY. This module imports
  only the data/core layers — never the scorer/engine — so the VM is incapable of running the model.
* **Bounded.** A per-IP rate limit keeps one caller from saturating the free 1-vCPU/1-GB box now
  that port 8000 faces the public internet (see ``_FixedWindowLimiter``).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ipo.core.logging import get_logger
from ipo.data.ingest.state import IngestStateStore
from ipo.data.store.repository import ParquetRepository
from ipo.series.store import SubscriptionSeriesStore
from ipo.vm.models import RecordsEnvelope, SeriesEnvelope, SeriesSample

_log = get_logger("ipo.vm.server")

_CONTEXT_REL = ("context", "ipo_context.json")

# Per-IP rate limit. The box is Always-Free (1 OCPU / 1 GB) on a public IP, so one scraper could
# otherwise starve the desktop fleet it exists to serve. Deliberately DEPENDENCY-FREE and in-memory:
# uvicorn runs a SINGLE worker here (scripts/run_vm_server.py calls uvicorn.run with no --workers),
# so a process-local counter is coherent — no Redis needed. A library (slowapi et al) would also be
# dead weight in every shipped .exe, since this module is a PyInstaller hidden import the desktop
# build carries but never executes.
#
# 60/min is deliberately generous vs. real use: the app pulls /records + /context once per ~30-min
# ingest cycle (2 requests per user per half hour). It is set for CGNAT, not for one user — Indian
# mobile carriers put many subscribers behind one public IP, and that shared IP must never trip the
# limit. It still stops a naive scraper dead.
_RATE_LIMIT_REQUESTS = 60
_RATE_LIMIT_WINDOW_SEC = 60.0
_RATE_LIMIT_MAX_TRACKED = 20_000


class _FixedWindowLimiter:
    """Bounded, process-local, per-key fixed-window request counter.

    Memory is capped on purpose: an unbounded ``{ip: state}`` dict is itself a way to kill a 1 GB
    box (spoofed sources would grow it without limit), so expired windows are pruned once the dict
    exceeds ``max_tracked`` and the whole table is dropped if pruning cannot get back under the cap.
    """

    def __init__(self, limit: int, window: float, max_tracked: int) -> None:
        self._limit = limit
        self._window = window
        self._max_tracked = max_tracked
        self._windows: dict[str, tuple[float, int]] = {}

    def check(self, key: str, now: float) -> tuple[float | None, bool]:
        """Count a hit; return ``(retry_after_seconds | None, is_first_rejection)``."""
        start, count = self._windows.get(key, (now, 0))
        if now - start >= self._window:  # window elapsed → start a fresh one
            start, count = now, 0
        count += 1
        self._windows[key] = (start, count)
        if len(self._windows) > self._max_tracked:
            self._prune(now)
        if count > self._limit:
            return max(1.0, self._window - (now - start)), count == self._limit + 1
        return None, False

    def _prune(self, now: float) -> None:
        for key in [k for k, (start, _) in self._windows.items() if now - start >= self._window]:
            del self._windows[key]
        if len(self._windows) > self._max_tracked:
            self._windows.clear()  # pathological flood: reset rather than grow without bound


def create_vm_app(data_dir: Path) -> FastAPI:
    """Build the VM's GET-only read-API over the stores in ``data_dir`` (no engine, no writes)."""
    app = FastAPI(title="IPO Advisor — VM data plane (read-only)", version="0.1.0")

    limiter = _FixedWindowLimiter(
        _RATE_LIMIT_REQUESTS, _RATE_LIMIT_WINDOW_SEC, _RATE_LIMIT_MAX_TRACKED
    )

    # Registered BEFORE CORS on purpose: Starlette runs the LAST-added middleware outermost, so
    # this ordering leaves CORS wrapping the limiter — a 429 still carries CORS headers instead
    # of looking like an opaque cross-origin failure to a browser client.
    @app.middleware("http")
    async def _rate_limit(request: Request, call_next):  # type: ignore[no-untyped-def]
        client = request.client
        key = client.host if client is not None else "unknown"
        retry_after, first_rejection = limiter.check(key, time.monotonic())
        if retry_after is not None:
            # Logged only on the transition into limiting — logging every rejected request would
            # turn a flood into a second flood (disk), which is the thing being defended against.
            if first_rejection:
                _log.warning("vm_rate_limited", extra={"client": key})
            return JSONResponse(
                {"detail": "rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(int(retry_after))},
            )
        return await call_next(request)

    # GET-only across origins: the app reads cross-origin; no other verb is allowed (never mutates).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness probe (the app's fallback trigger checks this)."""
        return {"status": "ok"}

    @app.get("/records", response_model=RecordsEnvelope)
    def records() -> RecordsEnvelope:
        """Every stored IPO record + the last-successful-ingest timestamp (freshness travels along).

        Read fresh from disk each call so a fetch job's write is served immediately. The app pulls
        these and scores LOCALLY — the VM never runs the model.

        A corrupt/torn records store degrades to an empty list (``ParquetRepository`` logs it as
        ``records_read_failed`` and sets ``records_degraded``); when that happens ``refreshed_at``
        is nulled so a stale success time is never presented as current — the same honest-empty
        discipline as ``/context``. A genuinely empty-but-fresh ingest keeps its real
        ``last_success``.
        """
        repo = ParquetRepository(data_dir)
        state = IngestStateStore(data_dir / "ingest_state.json").current()
        refreshed_at = None if repo.records_degraded else state.last_success
        return RecordsEnvelope(refreshed_at=refreshed_at, records=repo.list_all())

    @app.get("/context")
    def context() -> dict[str, Any]:
        """The Upstox per-IPO context cache verbatim (already ``{refreshed_at, ipos}``).

        Missing or corrupt → ``{refreshed_at: None, ipos: {}}`` so the app degrades honestly rather
        than erroring; the app's own ``field_state`` rule then reads the freshness the same way it
        does for the local cache.
        """
        path = data_dir.joinpath(*_CONTEXT_REL)
        if not path.is_file():
            return {"refreshed_at": None, "ipos": {}}  # normal dark-ship state (no cache yet)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            # A CORRUPT cache served as "empty" is a failure disguised as genuine absence — name it,
            # so a VM-side context problem isn't indistinguishable from "no registrar/RHP yet".
            _log.warning("vm_context_read_failed", extra={"error": str(exc)})
            return {"refreshed_at": None, "ipos": {}}
        if not isinstance(payload, dict):
            _log.warning("vm_context_malformed", extra={"type": type(payload).__name__})
            return {"refreshed_at": None, "ipos": {}}
        return payload

    @app.get("/subscription-series", response_model=SeriesEnvelope)
    def subscription_series(ipo_id: str) -> SeriesEnvelope:
        """ONE IPO's banked subscription trajectory (v3-DP DP-2), oldest sample first.

        ``ipo_id`` is a REQUIRED query parameter, not an optional filter. Every other route returns
        current state — roughly one small row per IPO — whereas this one returns a time series, so
        returning the whole store would hand a growing multi-IPO blob to a 1 vCPU / 1 GB box on
        every detail-page open. One IPO per request is the design, not a convenience. FastAPI turns
        a missing ``ipo_id`` into a 422 by itself: that is the one genuine CLIENT error here, and it
        is deliberately distinct from a valid request for an IPO that simply has no series.

        Read fresh from disk each call, like ``/records``, so a recorder write is served immediately
        with no cache to go stale.

        Degrades honestly in every other case, because for MONTHS the common answer is "nothing
        recorded": an unknown id, an IPO that closed before recording began, an unreadable file, or
        an id unsafe as a filename all return an empty-but-valid envelope rather than a 404 or a
        500. ``SubscriptionSeriesStore.read`` already logs the corrupt case loudly, so genuine
        absence and a real fault stay distinguishable in the log even though both read as empty on
        the wire (the same discipline as ``/context``).

        **The B1 wall still holds here.** This serves the trajectory to a DISPLAY; it does not, and
        must not, become a path by which the series reaches the scorer. The route is data-only, like
        the rest of this module, and the import-boundary test keeps that structural.
        """
        samples = SubscriptionSeriesStore(data_dir).read(ipo_id)
        wire = [
            SeriesSample(
                schema_version=s.schema_version,
                captured_at=s.captured_at,
                source_update_time=s.source_update_time,
                qib_sub=s.qib_sub,
                nii_sub=s.nii_sub,
                snii_sub=s.snii_sub,
                bnii_sub=s.bnii_sub,
                retail_sub=s.retail_sub,
                total_sub=s.total_sub,
            )
            for s in samples
        ]
        # Per-IPO freshness, derived from the DATA rather than the file's mtime: mtime is an
        # artifact of the filesystem (a restore, a `cp`, an rsync all rewrite it) whereas
        # captured_at is the reading's own truth and survives being moved. None for an empty series
        # — honestly "nothing recorded", not "recorded at the epoch".
        refreshed_at = max((s.captured_at for s in wire), default=None)
        return SeriesEnvelope(refreshed_at=refreshed_at, ipo_id=ipo_id, samples=wire)

    return app
