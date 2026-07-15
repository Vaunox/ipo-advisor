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
* ``GET /transitions``      — the durable verdict-change log (most-recent-first) for the alert
  center history; ``/transitions/{ipo_id}`` filters to one IPO's detail log.
* ``GET /calibration``      — the held-out (walk-forward OOS) reliability report + live gate/
  version, for the History reliability diagram. Held-out, never an in-sample recompute.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ipo.core.types import Verdict
from ipo.data.ingest.state import IngestStateStore
from ipo.service.calibration import load_calibration_view
from ipo.service.engine import VerdictEngine
from ipo.service.ipo_context import ContextStore, build_allotment_view, build_ipo_context
from ipo.service.views import (
    AllotmentView,
    CalibrationView,
    HistoryRow,
    IpoContextView,
    IPODetail,
    IPOListRow,
    StatusView,
    VerdictTransitionView,
)


def create_app(
    engine: VerdictEngine,
    *,
    calibration_report_path: Path | None = None,
    ingest_state: IngestStateStore | None = None,
    context_store: ContextStore | None = None,
) -> FastAPI:
    """Build the read-only advisory API over a composed ``VerdictEngine``.

    ``calibration_report_path`` points at the persisted held-out reliability report
    (``models/reliability.json``); when absent, ``/calibration`` serves gate/version with empty
    bins (it never fabricates a calibration curve).

    ``ingest_state`` (v3 BUG 1 / Defect 2) is the live-ingest freshness store ``/status`` serves;
    when absent (no live feed wired) ``/status`` reports ``live_ingest=false`` with null
    timestamps — it never invents a freshness it cannot prove.

    ``context_store`` (v3 V3-5/V3-6) is the display-only per-IPO Upstox context cache the
    ``/allotment`` tab and ``/context/{id}`` read (registrar, RHP link, …). When absent both report
    ``available=false`` honestly. It is a read of a store entirely separate from ``IPORecord`` —
    context data never reaches the model.
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

    @app.get("/status", response_model=StatusView)
    def status() -> StatusView:
        """Live-ingest freshness — the honest "how fresh is this?" the UI binds its clock to.

        ``last_successful_ingest`` reflects the last *confirmed-good* NSE pull and nothing else (v3
        BUG 1 / Defect 2). It advances only on a real fetch — never on this read, never on app open.
        A failing feed leaves it stale while ``last_attempt_ok`` goes false, so the UI can say "last
        successful pull Xh ago — retrying" instead of implying freshness. This is a read of recorded
        state, not a trigger — reading ``/status`` never causes an ingest.
        """
        if ingest_state is None:
            return StatusView(
                live_ingest=False,
                last_successful_ingest=None,
                last_attempt=None,
                last_attempt_ok=None,
            )
        s = ingest_state.current()
        return StatusView(
            live_ingest=True,
            last_successful_ingest=s.last_success,
            last_attempt=s.last_attempt,
            last_attempt_ok=s.last_attempt_ok,
            records_source=s.source,
            context_source=s.context_source,
        )

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
    def history(
        stt: float | None = None, dp: float | None = None, oth: float | None = None
    ) -> list[HistoryRow]:
        """Every listed IPO's point-in-time verdict paired with its actual net-of-cost outcome.

        Read-only accountability data for the History view + calibration scorecard: the verdict is
        verbatim ``verdict_for`` (point-in-time), the outcome is the model's own net-of-cost label.
        ``stt``/``dp``/``oth`` optionally override the operator's broker sell-costs for the
        net-of-cost display only — never a verdict or a probability.
        """
        return engine.history(stt=stt, dp=dp, oth=oth)

    @app.get("/transitions", response_model=list[VerdictTransitionView])
    def transitions() -> list[VerdictTransitionView]:
        """Every recorded verdict change (most-recent-first), for the alert center history.

        Verbatim from the durable transition log — each row is what the engine emitted at that
        clock, name-joined for display. ``crossed_into_apply`` marks the APPLY crossings alerted.
        """
        return engine.transitions()

    @app.get("/transitions/{ipo_id}", response_model=list[VerdictTransitionView])
    def transitions_for(ipo_id: str) -> list[VerdictTransitionView]:
        """One IPO's verdict-change history, most-recent-first; 404 if the IPO is unknown."""
        if engine.get_record(ipo_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown ipo_id: {ipo_id}")
        return engine.transitions(ipo_id)

    @app.get("/allotment", response_model=AllotmentView)
    def allotment() -> AllotmentView:
        """IPOs at/past the allotment stage joined with the registrar cache (v3 V3-6, display-only).

        Read-only routing convenience: registrar name + a deep-link to the registrar's own
        allotment-check portal + a public grievance contact. The registrar data comes from a store
        entirely separate from the scoring path — it is never a model input. Degrades honestly:
        ``available=false`` when no cache is loaded; per-IPO ``registrar=null`` when not yet
        published. Never handles a PAN — the tab links out to the registrar's own site.
        """
        if context_store is None:
            return AllotmentView(available=False, refreshed_at=None, rows=[])
        return build_allotment_view(engine.list_records(), context_store)

    @app.get("/context/{ipo_id}", response_model=IpoContextView)
    def ipo_context(ipo_id: str) -> IpoContextView:
        """One IPO's display-only Upstox context — the RHP link (+ its freshness state) (v3 V3-5).

        Read-only: joins the record with the per-IPO context cache. The RHP is the Red Herring
        Prospectus specifically (labelled as such in the UI). Degrades honestly — ``rhp_state``
        distinguishes "not filed yet" from "cache is stale". Context data comes from a store apart
        from the scoring path; it is never a model input. 404 if the IPO is unknown.
        """
        record = engine.get_record(ipo_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"unknown ipo_id: {ipo_id}")
        if context_store is None:
            return IpoContextView(
                ipo_id=ipo_id,
                available=False,
                refreshed_at=None,
                rhp_url=None,
                rhp_state="not_loaded",
                lot_size=None,
                lot_state="not_loaded",
                isin=None,
                isin_state="not_loaded",
                industry=None,
                industry_state="not_loaded",
                registrar=None,
                registrar_state="not_loaded",
            )
        return build_ipo_context(record, context_store)

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
