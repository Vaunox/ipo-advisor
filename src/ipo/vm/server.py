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
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ipo.data.ingest.state import IngestStateStore
from ipo.data.store.repository import ParquetRepository
from ipo.vm.models import RecordsEnvelope

_CONTEXT_REL = ("context", "ipo_context.json")


def create_vm_app(data_dir: Path) -> FastAPI:
    """Build the VM's GET-only read-API over the stores in ``data_dir`` (no engine, no writes)."""
    app = FastAPI(title="IPO Advisor — VM data plane (read-only)", version="0.1.0")

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
        """
        repo = ParquetRepository(data_dir)
        state = IngestStateStore(data_dir / "ingest_state.json").current()
        return RecordsEnvelope(refreshed_at=state.last_success, records=repo.list_all())

    @app.get("/context")
    def context() -> dict[str, Any]:
        """The Upstox per-IPO context cache verbatim (already ``{refreshed_at, ipos}``).

        Missing or corrupt → ``{refreshed_at: None, ipos: {}}`` so the app degrades honestly rather
        than erroring; the app's own ``field_state`` rule then reads the freshness the same way it
        does for the local cache.
        """
        path = data_dir.joinpath(*_CONTEXT_REL)
        if not path.is_file():
            return {"refreshed_at": None, "ipos": {}}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {"refreshed_at": None, "ipos": {}}
        return payload if isinstance(payload, dict) else {"refreshed_at": None, "ipos": {}}

    return app
