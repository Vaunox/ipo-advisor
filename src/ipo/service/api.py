"""Advisory-only REST API — Phase 6, a THIN reader over the VerdictEngine.

Read-only endpoints that return exactly what the engine produced. The API never re-scores,
re-derives a probability, or adds a second scoring path: the only probability that can appear
is the one the gated calibrator blessed (Inviolable Rule 1), and it passes through
serialization unchanged — ``None`` with the uncalibrated banner if the gate has not passed.

There are deliberately NO order/action endpoints and no mutating verbs: the system is
advisory only (Inviolable Rule 6).

Endpoints:
* ``GET /health``           — liveness.
* ``GET /ipos``             — verdicts for all stored IPOs (verdicts only).
* ``GET /board``            — list-view rows: each IPO's display metadata + its verdict, one read.
* ``GET /ipo/{ipo_id}``     — the record + verdict + point-in-time features + signed
  contributions (read-only enrichment for the detail view; the verdict is verbatim).
* ``GET /verdict/{ipo_id}`` — the verdict alone.
* ``GET /history``          — every listed IPO's point-in-time verdict + actual net-of-cost
  outcome (read-only accountability for the History view / calibration scorecard).
* ``GET /calibration``      — the held-out (walk-forward OOS) reliability report + live gate/
  version, for the History reliability diagram. Held-out, never an in-sample recompute.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ipo.core.types import Verdict
from ipo.service.calibration import load_calibration_view
from ipo.service.engine import VerdictEngine
from ipo.service.views import CalibrationView, HistoryRow, IPODetail, IPOListRow


def create_app(engine: VerdictEngine, *, calibration_report_path: Path | None = None) -> FastAPI:
    """Build the read-only advisory API over a composed ``VerdictEngine``.

    ``calibration_report_path`` points at the persisted held-out reliability report
    (``models/reliability.json``); when absent, ``/calibration`` serves gate/version with empty
    bins (it never fabricates a calibration curve).
    """
    app = FastAPI(title="IPO Listing-Gains Advisor", version="0.1.0")

    # The engine is a local sidecar bound to 127.0.0.1 and read-only (GET only, no credentials),
    # so permissive CORS is safe and lets the Electron renderer (file:// / dev localhost) reach it
    # cross-origin on the sidecar's chosen free port. It is NOT a public server.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok"}

    @app.get("/ipos", response_model=list[Verdict])
    def ipos() -> list[Verdict]:
        """Return the engine's verdict for every stored IPO (verbatim)."""
        return engine.verdicts()

    @app.get("/board", response_model=list[IPOListRow])
    def board() -> list[IPOListRow]:
        """The list view's rows: each stored IPO's display metadata + its verdict (read-only)."""
        return engine.board()

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

    @app.get("/calibration", response_model=CalibrationView)
    def calibration() -> CalibrationView:
        """The held-out (walk-forward OOS) reliability report + live gate/version (read-only).

        The bins/metrics are the honest out-of-sample calibration (never in-sample); the gate and
        version are read live from the calibrator. Powers the History reliability diagram.
        """
        return load_calibration_view(
            calibration_report_path,
            version=engine.calibrator_version,
            gate_passed=engine.calibrator_gate_passed,
        )

    return app
