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
* ``GET /ipo/{ipo_id}``     — the record + verdict + point-in-time features + signed
  contributions (read-only enrichment for the detail view; the verdict is verbatim).
* ``GET /verdict/{ipo_id}`` — the verdict alone.
* ``GET /history``          — every listed IPO's point-in-time verdict + actual net-of-cost
  outcome (read-only accountability for the History view / calibration scorecard).
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from ipo.core.types import Verdict
from ipo.service.engine import VerdictEngine
from ipo.service.views import HistoryRow, IPODetail


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

    @app.get("/ipo/{ipo_id}", response_model=IPODetail)
    def ipo(ipo_id: str) -> IPODetail:
        """Return the record + verdict + point-in-time features + signed contributions, or 404.

        Enriched (read-only) so the detail view can render the contribution breakdown, the feature
        values, and the cold-market flag. The ``verdict`` field is verbatim ``verdict_for`` — the
        extra fields are the *same* computation's inputs/explanation, never a re-score.
        """
        record = engine.get_record(ipo_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"unknown ipo_id: {ipo_id}")
        return engine.detail(record)

    @app.get("/history", response_model=list[HistoryRow])
    def history() -> list[HistoryRow]:
        """Every listed IPO's point-in-time verdict paired with its actual net-of-cost outcome.

        Read-only accountability data for the History view + calibration scorecard: the verdict is
        verbatim ``verdict_for`` (point-in-time), the outcome is the model's own net-of-cost label.
        """
        return engine.history()

    return app
