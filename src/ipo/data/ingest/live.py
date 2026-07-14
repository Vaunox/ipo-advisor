"""Live NSE ingestion — turn the running app's static store into a live one (Phase 7 follow-up).

Fetches the exchange's **current/active** IPOs + per-category subscription and upserts them as
``IPORecord``s the engine scores as-of close. This is the runtime ``refresh`` the scheduler was
designed for (``build_service(refresh=...)``) but which shipped unset — the app served frozen demo
data. Only decision-time facts NSE serves officially are used: symbol/dates/price band + QIB/NII/
retail (+ sNII/bNII/overall). Anchor quality, valuation and OFS have no official live feed, so they
stay ``None`` — the engine still scores (``qib_sub`` is the only critical feature), just with less
context, and abstains until the book closes.

Robustness: a network/parse failure of one issue is skipped; a failure of the whole fetch returns 0
and is logged — a live-data hiccup must never crash the sidecar (it degrades to the last store).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from pydantic import ValidationError

from ipo.core.calendar import now_ist
from ipo.core.constants import SEGMENT_MAINBOARD
from ipo.core.interfaces import Repository
from ipo.core.logging import get_logger
from ipo.core.types import IPORecord, Segment
from ipo.data.ingest.state import IngestStateStore
from ipo.data.sources.base import SourceError
from ipo.data.sources.nse import NseClient, NseCurrentIssue, NseSubscription

_log = get_logger("ipo.data.ingest.live")


def build_live_records(
    client: NseClient, *, clock: Callable[[], datetime] = now_ist
) -> list[IPORecord]:
    """Fetch current + forthcoming mainboard issues + subscription and build ``IPORecord``s.

    Merges NSE's ``ipo-current-issue`` (active / just-closed) with ``all-upcoming-issues``
    (forthcoming) so an IPO reaches the Upcoming calendar as soon as NSE lists it with a price band
    — not only once it opens. For a symbol in both feeds the current-issue entry wins (fresher,
    subscription-eligible). Raises ``SourceError`` only if the current-issues fetch itself fails; a
    forthcoming-feed failure degrades to current-only; a per-issue subscription or validation
    failure is skipped. SME issues are excluded.
    """
    issues = client.current_issues()
    try:
        upcoming = client.upcoming_issues()
    except SourceError:
        upcoming = []  # forthcoming feed is best-effort; current issues still ingest

    # Dedupe by symbol; the current-issue entry (iterated last) wins over the forthcoming one.
    merged: dict[str, NseCurrentIssue] = {}
    for issue in (*upcoming, *issues):
        merged[issue.symbol.upper()] = issue

    records: list[IPORecord] = []
    for issue in merged.values():
        if issue.segment != SEGMENT_MAINBOARD:
            continue  # SME excluded (Locked decision)
        if issue.price_band_high is None or issue.open_date is None or issue.close_date is None:
            continue  # not enough to build a valid record yet
        try:
            sub = client.subscription(issue.symbol, force=True)
        except SourceError:
            sub = NseSubscription(qib=None, nii=None, retail=None, total=None)
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
                    captured_at=clock(),
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
            except SourceError:
                prices = None
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
    """
    attempt = clock()
    ok = True
    error: str | None = None
    try:
        records = build_live_records(client, clock=clock)
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
