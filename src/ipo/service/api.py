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

from ipo.core.logging import get_logger
from ipo.core.types import Verdict
from ipo.data.ingest.state import IngestStateStore
from ipo.service.calibration import load_calibration_view
from ipo.service.engine import VerdictEngine
from ipo.service.ipo_context import ContextStore, build_allotment_view, build_ipo_context
from ipo.service.logs import clamp_limit, file_history, ring_tail
from ipo.service.views import (
    AllotmentView,
    CalibrationView,
    HistoryRow,
    IpoContextView,
    IPODetail,
    IPOListRow,
    LogsView,
    SeriesSampleView,
    SeriesView,
    StatusView,
    VerdictTransitionView,
)
from ipo.vm.client import VmClient, VmUnavailable

_log = get_logger("ipo.service.api")


def create_app(
    engine: VerdictEngine,
    *,
    calibration_report_path: Path | None = None,
    ingest_state: IngestStateStore | None = None,
    context_store: ContextStore | None = None,
    log_dir: Path | None = None,
    vm_client: VmClient | None = None,
) -> FastAPI:
    """Build the read-only advisory API over a composed ``VerdictEngine``.

    ``calibration_report_path`` points at the persisted held-out reliability report
    (``models/reliability.json``); when absent, ``/calibration`` serves gate/version with empty
    bins (it never fabricates a calibration curve).

    ``ingest_state`` (v3 BUG 1 / Defect 2) is the live-ingest freshness store ``/status`` serves;
    when absent (no live feed wired) ``/status`` reports ``live_ingest=false`` with null
    timestamps — it never invents a freshness it cannot prove.

    ``vm_client`` (v3-DP DP-3a) is the SAME VM client the 30-min data-plane cycle uses — hoisted to
    one construction site and passed to both, so there is one home for the VM connection rather than
    two clients that could drift apart. It is used ONLY by ``/subscription-series/{ipo_id}``, an
    on-demand pass-through; nothing here participates in the ingest cycle. Absent → that route
    reports ``not_loaded`` and the app behaves exactly as before the VM existed.

    ``context_store`` (v3 V3-5/V3-6) is the display-only per-IPO Upstox context cache the
    ``/allotment`` tab and ``/context/{id}`` read (registrar, RHP link, …). When absent both report
    ``available=false`` honestly. It is a read of a store entirely separate from ``IPORecord`` —
    context data never reaches the model.
    """
    app = FastAPI(title="IPO Listing-Gains Advisor", version="0.1.0")

    # Permissive CORS here is a DELIBERATE, considered accept (code-review #10 — won't-fix), not
    # an oversight. This engine is a LOCAL sidecar: bound to 127.0.0.1 (not network-reachable),
    # GET-only (it cannot mutate anything — Invariant 4), and credential-less (no cookies/auth, so
    # no CSRF or session surface). The packaged app loads from file://, whose Origin serializes to
    # the literal "null" — there is no clean origin to allowlist, so "*" is the honest value, not a
    # lazy one. The only residual vector is a local browser page reading non-secret, public IPO
    # data — negligible. If results are ever paywalled, the plan is to move the engine SERVER-SIDE
    # behind real auth (cf. vm/server.py, a genuinely public server); CORS was never a sufficient
    # paywall boundary, so it is not the lever to tighten here.
    #
    # allow_headers is narrowed to the one header the client sends (client.ts: `accept`). This is
    # truthful config, not a functional gate: a GET carrying only `accept` is a CORS "simple"
    # request, so no preflight fires and allow_headers is never consulted for a real request — the
    # packaged app is unaffected.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # file:// Origin is "null" — no clean origin to pin (see note above)
        allow_methods=["GET"],
        allow_headers=["accept"],
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
            next_refresh_at=ingest_state.next_refresh(),
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

    @app.get("/subscription-series/{ipo_id}", response_model=SeriesView)
    def subscription_series(ipo_id: str) -> SeriesView:
        """One IPO's banked subscription trajectory, fetched live from the VM (v3-DP DP-3a).

        AN ON-DEMAND PASS-THROUGH, DELIBERATELY NOT CACHED AND NOT IN THE 30-MIN CYCLE. The series
        is per-IPO and many rows; most IPOs are never opened. Pre-fetching every IPO's trajectory
        each cycle — or keeping a local series store — would recreate exactly the volume problem
        DP-2 solved by scoping the VM route to one IPO. Read fresh per request instead, like
        ``/records`` reads fresh from disk: a recorder write is visible on the next open, with no
        cache layer to go stale.

        FOUR DISTINCT STATES, kept apart on purpose (see ``SeriesView``). The one that matters is
        ``not_recorded`` vs ``unavailable``: "nothing was ever banked for this IPO" and "we could
        not reach the VM" are different truths, and a chart conflating them would tell the user an
        absence it cannot vouch for. There is NO local fallback — the recorder is VM-only, so no
        local series exists to fall back to.

        Logged either way so it lands in ``engine.log`` and the V3-16 console: ``series_from_vm``
        on a successful fetch, ``vm_series_unavailable`` (warning) when the VM cannot answer —
        mirroring ``records_from_vm`` / ``vm_records_fallback_local``.

        404 if the IPO is unknown — a bad request, distinct from a known IPO with no series (200,
        ``not_recorded``). B1 wall: this serves a chart, never the scorer.
        """
        record = engine.get_record(ipo_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"unknown ipo_id: {ipo_id}")
        if vm_client is None:
            # Dark-ship: no VM configured, exactly as before the VM existed. Not an error, and not
            # "not_recorded" either — with no VM we have no basis to claim anything was or wasn't.
            return SeriesView(ipo_id=ipo_id, available=False, state="not_loaded")
        try:
            envelope = vm_client.fetch_series(ipo_id)
        except VmUnavailable as exc:
            _log.warning("vm_series_unavailable", extra={"ipo_id": ipo_id, "error": str(exc)})
            return SeriesView(ipo_id=ipo_id, available=False, state="unavailable")
        samples = [SeriesSampleView(**s.model_dump()) for s in envelope.samples]
        _log.info("series_from_vm", extra={"ipo_id": ipo_id, "samples": len(samples)})
        return SeriesView(
            ipo_id=ipo_id,
            available=True,
            # An answered-but-empty series is honest absence, NOT a failure.
            state="recorded" if samples else "not_recorded",
            # Per-IPO freshness, straight from DP-2's envelope — never the app-global clock.
            refreshed_at=envelope.refreshed_at,
            samples=samples,
        )

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

    @app.get("/logs", response_model=LogsView)
    def logs(
        since: int = 0, limit: int = 500, history: bool = False, before: str | None = None
    ) -> LogsView:
        """The debug console's read (v3 V3-16) — structured log entries (read-only).

        The console shows ONE continuous timeline; this endpoint serves its two ends:

        * Live tail (default): the in-memory ring buffer — entries with ``seq > since`` (so the
          client polls only what's new), newest ``limit``; ``last_seq`` is the cursor to send back.
        * Older history (``history=true``): the durable rotated files, entries with ``ts <= before``
          (the scroll-back cursor), newest ``limit`` — the client pages backward with this as it
          scrolls up, stitching disk onto the ring by timestamp.

        Every entry was redacted at write time (``core.logging.redacted_payload``), so no
        token/PAN/auth-header can appear. GET-only — reading never triggers anything (Invariants 4 &
        6); a window, not a control surface.
        """
        capped = clamp_limit(limit)
        if history:
            entries = (
                file_history(log_dir, limit=capped, before=before) if log_dir is not None else []
            )
            return LogsView(entries=entries, last_seq=0, source="history")
        entries, last_seq = ring_tail(since=since, limit=capped)
        return LogsView(entries=entries, last_seq=last_seq, source="ring")

    return app
