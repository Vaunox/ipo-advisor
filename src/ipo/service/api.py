"""Advisory-only REST API — Phase 6, a THIN reader over the VerdictEngine.

Read-only endpoints that return exactly what the engine produced. The API never re-scores,
re-derives a probability, or adds a second scoring path: the only probability that can appear
is the one the gated calibrator blessed (Inviolable Rule 1), and it passes through
serialization unchanged — ``None`` with the uncalibrated banner if the gate has not passed.

There are deliberately NO order/action endpoints and no mutating verbs: the system is
advisory only (Inviolable Rule 6).

Endpoints:
* ``GET /health``           — liveness.
* ``GET /ipos``             — verdicts for all stored IPOs.
* ``GET /ipo/{ipo_id}``     — the record plus its verdict.
* ``GET /verdict/{ipo_id}`` — the verdict alone.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from ipo.core.types import Verdict
from ipo.service.engine import VerdictEngine


def create_app(engine: VerdictEngine) -> FastAPI:
    """Build the read-only advisory API over a composed ``VerdictEngine``."""
    app = FastAPI(title="IPO Listing-Gains Advisor", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok"}

    @app.get("/ipos", response_model=list[Verdict])
    def ipos() -> list[Verdict]:
        """Return the engine's verdict for every stored IPO (verbatim)."""
        return engine.verdicts()

    @app.get("/verdict/{ipo_id}", response_model=Verdict)
    def verdict(ipo_id: str) -> Verdict:
        """Return the engine's verdict for one IPO, or 404 if it is not stored."""
        record = engine.get_record(ipo_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"unknown ipo_id: {ipo_id}")
        return engine.verdict_for(record)

    @app.get("/ipo/{ipo_id}")
    def ipo(ipo_id: str) -> dict[str, Any]:
        """Return the stored record together with its engine verdict, or 404."""
        record = engine.get_record(ipo_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"unknown ipo_id: {ipo_id}")
        return {"record": record, "verdict": engine.verdict_for(record)}

    return app
