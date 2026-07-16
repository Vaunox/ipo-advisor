"""API view models (DTOs) — read-only projections the API serializes.

These carry **no logic**: they package what the engine already computed so the front end can
render the detail view (the signed feature contributions behind the score, and the point-in-time
features behind the cold-market flag and the shown feature values) without any second scoring
path. Every field is verbatim engine output — the ``verdict`` here is byte-for-byte the one the
``/verdict`` endpoint returns for the same IPO (asserted in tests/integration/test_api.py).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from ipo.core.types import IPOFeatures, IPORecord, Verdict, VerdictType


class IPODetail(BaseModel):
    """One IPO's record + verdict + the features and signed contributions that produced it.

    ``contributions`` is the scorer's per-feature signed breakdown (Layer-3 transparency): each
    key is a named feature, each value its signed contribution to the raw score. It is the actual
    arithmetic behind ``verdict``, not a narrative — empty/partial when the engine abstained
    (a blind record is never scored). ``features`` are the same point-in-time inputs the verdict
    was scored on (regime flag-only, GMP absent).

    ``retail_allotment_odds`` (v2 A3) is a **separate, downstream, display-only estimate** — the
    approximate probability a minimum-lot retail application is allotted (``min(1, 1/retail_sub)``,
    a conservative proxy for a whole-lot lottery; see ``service.allotment``). It is computed
    entirely outside the scoring path and must be shown as an **estimate distinct from**
    ``verdict.probability`` (the calibrated P(positive listing)) — the two are different numbers.
    ``None`` when the retail multiple is unknown.
    """

    record: IPORecord
    verdict: Verdict
    features: IPOFeatures
    contributions: dict[str, float]
    retail_allotment_odds: float | None = None


class IPOListRow(BaseModel):
    """One row for the list/board view: display metadata + the verdict, in a single read.

    Combines the record's display fields (name, segment, size, key dates — the front end derives
    the live status from the dates) with the engine's verdict verbatim, so the list renders without
    an N-per-IPO fetch. ``verdict``/``probability`` are byte-for-byte ``verdict_for``; the record
    fields are display-only and never feed a score.
    """

    ipo_id: str
    name: str
    segment: str
    issue_size_cr: float | None
    ofs_fraction: float | None
    issue_pe: float | None
    peer_median_pe: float | None
    open_date: date
    close_date: date
    listing_date: date | None
    verdict: VerdictType
    probability: float | None
    reason: str
    watch: list[str]
    kill_flags: list[str]
    # v3 finding-④: True when the Live→History resolution is OVERDUE (silently stranded) — the book
    # closed but no listing_date was ever stamped past the expected day + buffer, or a stamped row's
    # price never backfilled. Lets the awaiting-listing surface name the strand, not hide it.
    listing_overdue: bool = False


class HistoryRow(BaseModel):
    """One past IPO: its point-in-time verdict paired with the actual net-of-cost outcome.

    ``verdict``/``probability`` are what the engine would have emitted at the decision clock
    (subscription-close EOD) from as-of features only — the listing label is never read into a
    feature (Inviolable Rule 2), so predicted and actual stay independent. ``net_return`` is the
    model's own target basis (net-of-cost listing-day return, the flip exit at the listing open),
    and ``listed_positive`` its binary label. This is the honest "predicted vs actual" the
    History view and the calibration scorecard are built from.
    """

    ipo_id: str
    name: str
    listing_date: date | None
    verdict: VerdictType
    probability: float | None
    net_return: float
    gross_return: float
    listed_positive: bool


class VerdictTransitionView(BaseModel):
    """One verdict change for the alert center + detail history: the persisted transition + name.

    Verbatim from the transition log (recorded as the engine emitted it) with the IPO's display
    name joined for rendering — no re-score. ``from_verdict`` is ``None`` for a first observation;
    ``crossed_into_apply`` is the APPLY crossing the alert center highlights.
    """

    ipo_id: str
    name: str
    asof: datetime
    from_verdict: VerdictType | None
    to_verdict: VerdictType
    probability: float | None
    crossed_into_apply: bool


class ReliabilityBinView(BaseModel):
    """One reliability-diagram bucket: mean predicted probability vs observed rate and count."""

    mean_predicted: float
    observed_rate: float
    count: int


class CalibrationView(BaseModel):
    """The calibration the History reliability diagram + scorecard render (read-only).

    The metrics and ``bins`` are the **held-out** walk-forward out-of-sample reliability (generated
    by scripts/run_reliability_export.py) — never an in-sample recompute, so the diagram shows the
    honest calibration (Inviolable Rule 1). ``version`` and ``gate_passed`` come live from the
    loaded calibrator. When no report has been generated, the metrics are ``None`` and ``bins`` is
    empty (``source`` says so) — the UI degrades gracefully rather than inventing a curve.
    """

    version: str
    gate_passed: bool
    source: str
    n: int
    base_rate: float | None
    ece: float | None
    brier: float | None
    auc: float | None
    bins: list[ReliabilityBinView]


class RegistrarInfo(BaseModel):
    """One IPO's registrar contact block (v3 V3-6) — public, mandated-disclosure business contact.

    Display/routing only — NEVER a model input (it is not an ``IPORecord`` field and the feature
    builder never sees it). ``website`` is the registrar's own allotment-check portal we deep-link
    out to (the user enters their PAN there, not in this app). ``contact_*`` is the registrar's
    public grievance channel. Every field is nullable — a not-yet-published registrar degrades to
    ``None``, never a fabricated value.
    """

    name: str | None = None
    short: str | None = None  # the registrar short code (e.g. "MUFG", "KFIN")
    website: str | None = None
    email: str | None = None
    contact_number: str | None = None
    contact_name: str | None = None


class AllotmentRow(BaseModel):
    """One IPO at/past the allotment stage: its lifecycle stage + its registrar (v3 V3-6).

    Display/routing only. ``stage`` is derived from the record's dates (book closed → awaiting
    allotment/listing; listed → listed).

    ``registrar_state`` makes the app do the reasoning the freshness line otherwise offloads to the
    user, so an absent registrar never lies about *why* it's absent:
      * ``present`` — ``registrar`` is populated.
      * ``unpublished`` — the cache is current (refreshed at/after this IPO opened) and still has no
        entry → the registrar genuinely isn't published yet.
      * ``stale`` — the cache predates this IPO's open date (we never looked) or is past the stale
        threshold → the absence is unproven; the UI says "stale — last refreshed {date}", not
        "not yet available".
      * ``not_loaded`` — no cache at all (the whole view is ``available=false``).
    """

    ipo_id: str
    name: str
    stage: str
    close_date: date
    listing_date: date | None
    registrar: RegistrarInfo | None
    registrar_state: str


class IpoContextView(BaseModel):
    """One IPO's display-only Upstox context for the detail page (v3 V3-5+) — never a model input.

    Carries the RHP link (V3-5), the bid ``lot_size`` (V3-8), the ``isin`` + ``industry`` reference
    fields (V3-11), and the registrar (shared with the Allotment tab); extend as V3-10 lands.
    ``isin``/``industry`` are plain display metadata (no source named, honest degradation via their
    ``*_state``). ``lot_size`` is Upstox's — NSE gives it
    on 0% of IPOs, so it is the sole source and the UI shows it as an INDICATIVE planning figure
    (``≈ N shares · approx ₹…``), never an exact reported value (a possibly-imprecise number must
    not wear an authoritative face; the app places no bids, so the broker enforces the true lot at
    application time). Each cached field is paired with its freshness
    state (``*_state``: present / unpublished / stale / not_loaded — see
    ``AllotmentRow.registrar_state``), so a missing RHP distinguishes "not filed yet" from "cache
    predates the filing" rather than a bare null. ``rhp_url`` is the *Red Herring Prospectus*
    specifically (the final offer document),
    labelled as such in the UI — not a generic "prospectus" and never the draft (DRHP was dropped as
    unusable: 1/28 populated and unjoinable — see docs/v3/V3_PROGRESS.md).
    """

    ipo_id: str
    available: bool
    refreshed_at: datetime | None
    rhp_url: str | None
    rhp_state: str
    lot_size: int | None
    lot_state: str
    isin: str | None
    isin_state: str
    industry: str | None
    industry_state: str
    registrar: RegistrarInfo | None
    registrar_state: str


class AllotmentView(BaseModel):
    """The Allotment tab payload (v3 V3-6) — read-only join of IPOs past close × registrar cache.

    ``available`` is False when no registrar cache has been loaded yet (fresh install, or the
    operator/VM has not run the refresh) — the tab says so honestly instead of showing blanks.
    ``refreshed_at`` is when the cache was last written by the refresh job. The registrar data
    reaches this view through a store that is entirely separate from ``IPORecord`` and the scoring
    path — it cannot become a feature (proven by the import-graph check).
    """

    available: bool
    refreshed_at: datetime | None
    rows: list[AllotmentRow]


class StatusView(BaseModel):
    """Live-ingest freshness (v3 BUG 1 / Defect 2) — the honest "how fresh is this?" for the UI.

    ``last_successful_ingest`` is the only value the UI may present as "Updated" — the timestamp of
    the last *confirmed-good* NSE pull, advancing solely on a real fetch (never on app open, render,
    or a local API read). ``last_attempt`` / ``last_attempt_ok`` describe the most recent try, so
    the UI can show a truthful "last successful pull Xh ago — retrying" when NSE is failing while
    the store is still served. ``live_ingest`` is False when the build has no live feed wired (the
    timestamps are then ``None`` by construction, not a swallowed failure).

    ``records_source`` / ``context_source`` (v3 V3-1) name which path served each store this cycle —
    ``"vm"`` | ``"local"`` | ``None`` (no VM configured). They let the fallback chip say the honest,
    per-store truth: on a VM outage records are ``local`` but **fresh** (a real re-scrape) while
    context is ``local`` but **aging** (the token is on the VM, so it can't be re-fetched) — not one
    blanket "VM unreachable" implying both are equally degraded. Freshness itself still lives on
    ``last_successful_ingest`` (records) and the context cache's timestamp; source is only a label.
    """

    live_ingest: bool
    last_successful_ingest: datetime | None
    last_attempt: datetime | None
    last_attempt_ok: bool | None
    records_source: str | None = None
    context_source: str | None = None
    # v3 QoL: when the next scheduled refresh fires — a tooltip-only hint. ``None`` whenever it
    # can't be honestly predicted (failing feed, VM fallback, or just after a manual refresh), so
    # the UI shows nothing rather than a guess. Never presented as freshness — that stays on
    # ``last_successful_ingest``.
    next_refresh_at: datetime | None = None


class LogsView(BaseModel):
    """The debug console's read (v3 V3-16) — recent structured log entries, already redacted.

    ``entries`` are ``{ts, level, message, …}`` dicts verbatim from the engine's own log (the ring
    buffer for the live tail, the rotated files for history); every value was redacted at write time
    (``core.logging.redacted_payload``), so no secret rides through. Heterogeneous by design — the
    ``extra`` fields differ per event — so each is an open dict, not a fixed schema. ``last_seq`` is
    the highest ring seq returned; the client passes it back as ``since`` to poll only what's new.
    ``source`` is ``"ring"`` (live tail) or ``"history"`` (rotated files).
    """

    entries: list[dict[str, Any]]
    last_seq: int
    source: str
