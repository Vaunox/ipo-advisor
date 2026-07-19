"""Live NSE ingestion — turn the running app's static store into a live one (Phase 7 follow-up).

Fetches the exchange's **current/active** IPOs + per-category subscription and upserts them as
``IPORecord``s the engine scores as-of close. This is the runtime ``refresh`` the scheduler was
designed for (``build_service(refresh=...)``) but which shipped unset — the app served frozen demo
data. Only decision-time facts NSE serves officially are used: symbol/dates/price band + QIB/NII/
retail (+ sNII/bNII/overall). Anchor quality, valuation and OFS have no official live feed, so they
stay ``None`` — the engine still scores (``qib_sub`` is the only critical feature), just with less
context, and abstains until the book closes.

Robustness: a per-issue subscription-fetch failure preserves the last-known book (or abstains
honestly when it can't be trusted), always logged — never a silent all-None that would change a
verdict; a per-issue validation failure is skipped; a failure of the whole fetch returns 0 and is
logged — a live-data hiccup must never crash the sidecar (it degrades to the last store).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime

from pydantic import ValidationError

from ipo.core.calendar import now_ist
from ipo.core.constants import SEGMENT_MAINBOARD
from ipo.core.interfaces import Repository
from ipo.core.logging import get_logger
from ipo.core.types import IPORecord, Segment
from ipo.data.ingest.state import IngestStateStore
from ipo.data.sources.base import SourceError
from ipo.data.sources.nse import NseClient, NseCurrentIssue, NseSubscription
from ipo.series.recorder import SeriesSink

_log = get_logger("ipo.data.ingest.live")


def _degrade_subscription(
    prior: IPORecord | None, close_date: date, now: datetime
) -> tuple[NseSubscription, datetime, str, bool]:
    """Decide what a *failed* per-IPO subscription fetch yields (v3 correctness fix).

    The old behavior silently substituted an all-None subscription: once the book is closed that
    made ``qib_sub`` None -> ``INSUFFICIENT_SIGNAL``, indistinguishable from an absent book,
    and ``upsert_many`` then CLOBBERED the last-known good value with None. Instead:

    * **Preserve** the prior subscription — carrying its ``captured_at`` so that timestamp keeps
      marking the last *successful* pull and the staleness clock stays honest — when we hold a real
      prior book (``prior.qib_sub`` is not None) AND either the book is still open (the value isn't
      scored yet, so keep it alive to survive to the close) OR the prior value was captured on/after
      the close date. Subscriptions build to the close-day peak, so a value from the close day
      or later is a conservative floor (it can only *understate* demand) or the final figure — a
      trustworthy proxy for the closing book.
    * **Abstain** (all-None -> INSUFFICIENT_SIGNAL) when there is no prior book, or the only prior
      value predates the close date. A pre-close-day figure can miss the close-day demand surge (QIB
      front-loads late), so scoring a confident verdict on it is the exact failure mode this guard
      exists to prevent — better to abstain honestly (the caller logs it) than to score stale data.

    Returns ``(subscription, captured_at, outcome, preserved)``; ``outcome`` is a slug for the
    structured log (and the future V3-16 console).
    """
    none_sub = NseSubscription(qib=None, nii=None, retail=None, total=None)
    if prior is None or prior.qib_sub is None:
        return none_sub, now, "abstained_no_prior_book", False
    book_open = now.date() < close_date
    # captured_at is stamped from now_ist() (IST-aware), so .date() is the IST calendar date — the
    # same basis as close_date (an NSE IST date).
    fresh_for_close = prior.captured_at.date() >= close_date
    if book_open or fresh_for_close:
        preserved_sub = NseSubscription(
            qib=prior.qib_sub,
            nii=prior.nii_sub,
            retail=prior.retail_sub,
            total=prior.overall_sub,
            nii_small=prior.nii_small_sub,
            nii_big=prior.nii_big_sub,
        )
        outcome = "preserved_awaiting_close" if book_open else "scored_on_preserved"
        return preserved_sub, prior.captured_at, outcome, True
    return none_sub, now, "abstained_stale_prior", False


def build_live_records(
    client: NseClient,
    *,
    clock: Callable[[], datetime] = now_ist,
    existing: Mapping[str, IPORecord] | None = None,
    sink: SeriesSink | None = None,
) -> list[IPORecord]:
    """Fetch current + forthcoming mainboard issues + subscription and build ``IPORecord``s.

    Merges NSE's ``ipo-current-issue`` (active / just-closed) with ``all-upcoming-issues``
    (forthcoming) so an IPO reaches the Upcoming calendar as soon as NSE lists it with a price band
    — not only once it opens. For a symbol in both feeds the current-issue entry wins (fresher,
    subscription-eligible). Raises ``SourceError`` only if the current-issues fetch itself fails; a
    forthcoming-feed failure degrades to current-only; a per-issue validation failure is skipped.

    A per-issue *subscription* fetch failure no longer silently zeroes the book: given ``existing``
    (the current store keyed by ``ipo_id``), the last-known subscription is preserved when it's a
    trustworthy proxy for the closing book, else the issue abstains honestly — always logged (see
    ``_degrade_subscription``). ``existing`` defaults to empty (no preserve, all-None on failure) so
    the happy path and direct callers are unaffected. SME issues are excluded.

    ``sink`` (v3-DP DP-1) is the forward series recorder, and defaults to ``None`` so this function
    behaves exactly as before for every caller that does not pass one. Only the VM's
    ``run_live_ingest.py`` passes a real sink — deliberately NOT ``refresh_from_nse`` itself, which
    is also the DESKTOP's local-fallback leaf, so an unconditional hook would turn every shipped
    ``.exe`` into a recorder during a VM outage and break "one writer, one home".
    """
    issues = client.current_issues()
    try:
        upcoming = client.upcoming_issues()
    except SourceError as exc:
        upcoming = []  # forthcoming feed is best-effort; current issues still ingest
        _log.warning("live_upcoming_feed_degraded", extra={"error": str(exc)})

    # Dedupe by symbol; the current-issue entry (iterated last) wins over the forthcoming one.
    merged: dict[str, NseCurrentIssue] = {}
    for issue in (*upcoming, *issues):
        merged[issue.symbol.upper()] = issue

    prior_by_id = existing or {}
    records: list[IPORecord] = []
    for issue in merged.values():
        if issue.segment != SEGMENT_MAINBOARD:
            continue  # SME excluded (Locked decision)
        if issue.price_band_high is None or issue.open_date is None or issue.close_date is None:
            continue  # not enough to build a valid record yet
        now = clock()
        try:
            snapshot = client.subscription_snapshot(issue.symbol, force=True)
            sub = snapshot.subscription
            captured = now
            if sink is not None:
                # v3-DP DP-1. THIS BRANCH ONLY — the `except` below synthesises a replay of the
                # PRIOR record stamped with the prior captured_at, and banking that would write a
                # fabricated sample indistinguishable from a real one. A failed fetch banks
                # nothing: an honest gap. `observe` never raises, and is wrapped regardless so a
                # recorder fault can never cost us a scoring record.
                try:
                    sink.observe(
                        ipo_id=issue.symbol.lower(),
                        symbol=issue.symbol,
                        captured_at=captured,
                        raw_content=snapshot.raw_content,
                        open_date=issue.open_date,
                        close_date=issue.close_date,
                        today=now.date(),
                    )
                except Exception as exc:  # noqa: BLE001 - recorder must never break ingest
                    _log.warning(
                        "series_observe_failed",
                        extra={"symbol": issue.symbol, "error": str(exc)},
                    )
        except SourceError as exc:
            # A transient sub-fetch failure must not silently zero (and clobber) the book. Preserve
            # last-known when it's a trustworthy proxy, else abstain honestly — but never silently.
            sub, captured, outcome, preserved = _degrade_subscription(
                prior_by_id.get(issue.symbol.lower()), issue.close_date, now
            )
            _log.warning(
                "live_subscription_fetch_failed",
                extra={
                    "symbol": issue.symbol,
                    "error": str(exc),
                    "preserved": preserved,
                    "outcome": outcome,
                },
            )
        try:
            records.append(
                IPORecord(
                    ipo_id=issue.symbol.lower(),
                    name=issue.company or issue.symbol,
                    segment=Segment(issue.segment),
                    price_band_low=issue.price_band_low or issue.price_band_high,
                    price_band_high=issue.price_band_high,
                    open_date=issue.open_date,
                    close_date=issue.close_date,
                    qib_sub=sub.qib,
                    nii_sub=sub.nii,
                    retail_sub=sub.retail,
                    nii_small_sub=sub.nii_small,
                    nii_big_sub=sub.nii_big,
                    overall_sub=sub.total,
                    captured_at=captured,
                )
            )
        except (ValidationError, ValueError) as exc:
            _log.warning("live_record_skipped", extra={"symbol": issue.symbol, "error": str(exc)})
    return records


# How long after listing we keep retrying the (throttle-prone) bhavcopy price backfill. The price is
# a label-only annotation, but a transient archive-host failure on the one cycle that stamps the
# listing must not lose it forever — so a just-listed issue whose price is still missing is re-tried
# for a bounded window, then left as-is (avoids re-fetching the master list for stale rows forever).
# Public because the listing-overdue detector (service.lifecycle) keys "stamped but never priced"
# off the SAME window — past it, resolution has given up, so the row is genuinely stranded.
PRICE_BACKFILL_DAYS = 10


def resolve_listings(
    repo: Repository, client: NseClient, *, clock: Callable[[], datetime] = now_ist
) -> int:
    """Mark stored issues that have LISTED — completing the Live → History lifecycle. Never raises.

    A live-ingested issue leaves the ``ipo-current-issue`` feed once it lists, so without this it
    would sit in Live forever with ``listing_date = None``. Here we take stored issues whose book
    has closed but that we haven't fully resolved, look them up in the (re-fetched) past-issues, and
    if listed stamp ``listing_date`` (+ listing-day open/close from the bhavcopy) — which drops the
    issue out of Live and into History. A row whose date is stamped but whose price is still missing
    is retried for ``PRICE_BACKFILL_DAYS`` so a throttled bhavcopy fetch isn't lost. Returns how
    many rows were changed.
    """
    today = clock().date()

    def needs_resolution(r: IPORecord) -> bool:
        if r.close_date >= today:
            return False  # book still open — not a lifecycle candidate
        if r.listing_date is None:
            return True  # closed but unmarked → resolve
        # marked listed but price still missing → retry the bhavcopy for a bounded window
        return r.listing_open is None and (today - r.listing_date).days <= PRICE_BACKFILL_DAYS

    awaiting = [r for r in repo.list_all() if needs_resolution(r)]
    if not awaiting:
        return 0
    try:
        past = {p.symbol.upper(): p for p in client.past_issues(force=True)}
    except SourceError as exc:
        _log.warning("listing_resolve_past_failed", extra={"error": str(exc)})
        return 0

    resolved = 0
    for record in awaiting:
        issue = past.get(record.ipo_id.upper())  # ipo_id is the NSE symbol, lower-cased
        if issue is None or issue.listing_date is None or issue.listing_date > today:
            continue  # not listed yet (or not on NSE)
        update: dict[str, object] = {}
        if record.listing_date is None:
            update["listing_date"] = issue.listing_date
        if record.listing_open is None:
            try:
                prices = client.listing_prices(issue.symbol, issue.listing_date)
            except SourceError as exc:
                prices = None
                # Stamped as listed but the price fetch failed — retried within PRICE_BACKFILL_DAYS,
                # and a persistent failure escalates to the OVERDUE_UNPRICED strand (finding-④). Log
                # each attempt so a flaky archive host isn't mistaken for "not listed yet".
                _log.warning(
                    "listing_price_backfill_failed",
                    extra={
                        "symbol": issue.symbol,
                        "listing_date": issue.listing_date.isoformat(),
                        "error": str(exc),
                    },
                )
            if prices is not None:
                update["listing_open"], update["listing_close"] = prices
        if not update:
            continue  # nothing new (price still unavailable) — don't rewrite an identical row
        try:
            repo.upsert(record.model_copy(update=update))
            resolved += 1
        except (ValidationError, ValueError) as exc:
            _log.warning(
                "listing_resolve_skipped", extra={"symbol": issue.symbol, "error": str(exc)}
            )
    if resolved:
        _log.info("listings_resolved", extra={"count": resolved})
    return resolved


def refresh_from_nse(
    repo: Repository,
    client: NseClient,
    *,
    clock: Callable[[], datetime] = now_ist,
    state: IngestStateStore | None = None,
    sink: SeriesSink | None = None,
) -> int:
    """Pull live current mainboard IPOs, resolve any that have listed, and upsert. Never raises.

    A whole-fetch failure (NSE unreachable, cookie/handshake, source drift) is logged and yields 0 —
    the app keeps serving the last known store rather than going dark. Listing resolution moves
    just-listed issues out of Live and into History.

    ``state`` (v3 BUG 1 / Defect 2), when supplied, records the freshness truth: every attempt sets
    ``last_attempt``, but ``last_success`` advances **only** when the NSE current-issues pull
    genuinely succeeds. Reaching NSE — not the record count — is what "fresh" means (a successful
    pull that finds no active IPOs is still a successful pull). Degrade-don't-crash is preserved;
    the failure is now *recorded* (visible) instead of silently swallowed.

    ``sink`` (v3-DP DP-1) rides the SAME fetch: one NSE call, two writes — current state is
    overwritten as it always has been, and the identical reading is appended to the forward series.
    It is only populated here; the caller flushes it AFTER this returns, so a series write can
    never sit between the fetch and the scoring upsert.
    """
    attempt = clock()
    ok = True
    error: str | None = None
    # Snapshot the store so a failed per-issue subscription fetch can preserve last-known values
    # instead of clobbering them with None (see build_live_records / _degrade_subscription).
    existing = {r.ipo_id: r for r in repo.list_all()}
    try:
        records = build_live_records(client, clock=clock, existing=existing, sink=sink)
    except SourceError as exc:
        _log.warning("live_refresh_failed", extra={"error": str(exc)})
        records = []
        ok = False
        error = str(exc)
    if records:
        repo.upsert_many(records)
    resolve_listings(repo, client, clock=clock)  # complete the lifecycle; never raises
    if state is not None:
        if ok:
            state.record_success(attempt)
        else:
            state.record_failure(attempt, error or "unknown ingest failure")
    _log.info("live_refresh_done", extra={"records": len(records), "ok": ok})
    return len(records)
