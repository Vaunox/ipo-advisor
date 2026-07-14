"""Live NSE ingestion — the orchestrator builds records from current issues, robustly, no network.

Uses a stub client (structurally an ``NseClient``) so the record-building and failure-handling
logic is deterministic and offline: mainboard-only, incomplete issues skipped, and a whole-fetch
failure degrades to zero records rather than raising (the sidecar must never crash on a hiccup).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import cast

from ipo.core.interfaces import Repository
from ipo.core.types import IPORecord, ListingLabel, Segment
from ipo.data.ingest.live import build_live_records, refresh_from_nse, resolve_listings
from ipo.data.sources.base import SourceError
from ipo.data.sources.nse import NseClient, NseCurrentIssue, NsePastIssue, NseSubscription


class _StubClient:
    """Duck-typed NseClient: canned current issues + subscription + past issues / listing prices."""

    def __init__(
        self,
        issues: list[NseCurrentIssue] | None,
        subs: dict[str, NseSubscription] | None = None,
        past: list[NsePastIssue] | None = None,
        prices: dict[str, tuple[float, float] | None] | None = None,
        upcoming: list[NseCurrentIssue] | None = None,
    ) -> None:
        self._issues = issues
        self._subs = subs or {}
        self._past = past
        self._prices = prices or {}
        self._upcoming = upcoming or []

    def current_issues(self) -> list[NseCurrentIssue]:
        if self._issues is None:
            raise SourceError("nse unreachable")
        return self._issues

    def upcoming_issues(self) -> list[NseCurrentIssue]:
        return self._upcoming

    def subscription(self, symbol: str, *, force: bool = False) -> NseSubscription:
        return self._subs.get(symbol, NseSubscription(qib=None, nii=None, retail=None, total=None))

    def past_issues(self, *, force: bool = False) -> list[NsePastIssue]:
        if self._past is None:
            raise SourceError("nse unreachable")
        return self._past

    def listing_prices(self, symbol: str, listing_day: date) -> tuple[float, float] | None:
        return self._prices.get(symbol)


class _Repo:
    """Minimal in-memory Repository; upserts replace by ipo_id like the real ParquetRepository."""

    def __init__(self, records: list[IPORecord] | None = None) -> None:
        self.records: list[IPORecord] = list(records or [])

    def _put(self, record: IPORecord) -> None:
        for i, existing in enumerate(self.records):
            if existing.ipo_id == record.ipo_id:
                self.records[i] = record
                return
        self.records.append(record)

    def upsert(self, record: IPORecord) -> None:
        self._put(record)

    def upsert_many(self, records: list[IPORecord]) -> None:
        for record in records:
            self._put(record)

    def get(self, ipo_id: str) -> IPORecord | None:
        return next((r for r in self.records if r.ipo_id == ipo_id), None)

    def list_all(self) -> list[IPORecord]:
        return list(self.records)

    def save_labels(self, labels: list[ListingLabel]) -> None: ...

    def load_labels(self) -> list[ListingLabel]:
        return []


def _client(
    issues: list[NseCurrentIssue] | None,
    subs: dict[str, NseSubscription] | None = None,
    past: list[NsePastIssue] | None = None,
    prices: dict[str, tuple[float, float] | None] | None = None,
    upcoming: list[NseCurrentIssue] | None = None,
) -> NseClient:
    return cast(NseClient, _StubClient(issues, subs, past, prices, upcoming))


_KNACK = NseCurrentIssue(
    symbol="KNACK",
    company="Knack Packaging Limited",
    segment="mainboard",
    price_band_low=161.0,
    price_band_high=170.0,
    open_date=date(2026, 7, 1),
    close_date=date(2026, 7, 3),
)
_SME = NseCurrentIssue(
    symbol="ICELCO",
    company="IC Electricals",
    segment="sme",
    price_band_low=None,
    price_band_high=None,
    open_date=date(2026, 7, 3),
    close_date=date(2026, 7, 7),
)


def test_build_live_records_mainboard_only() -> None:
    subs = {
        "KNACK": NseSubscription(
            qib=3.48, nii=19.22, retail=4.23, total=7.21, nii_small=17.13, nii_big=20.27
        )
    }
    recs = build_live_records(_client([_KNACK, _SME], subs))
    assert [r.ipo_id for r in recs] == ["knack"]  # SME excluded
    r = recs[0]
    assert r.name == "Knack Packaging Limited"
    assert (r.qib_sub, r.nii_sub, r.retail_sub, r.overall_sub) == (3.48, 19.22, 4.23, 7.21)
    assert (r.nii_small_sub, r.nii_big_sub) == (17.13, 20.27)
    assert (r.price_band_low, r.price_band_high) == (161.0, 170.0)


def test_build_live_records_skips_incomplete() -> None:
    incomplete = NseCurrentIssue(
        symbol="X",
        company="X Ltd",
        segment="mainboard",
        price_band_low=None,
        price_band_high=None,  # no band → can't build
        open_date=date(2026, 7, 1),
        close_date=date(2026, 7, 3),
    )
    assert build_live_records(_client([incomplete])) == []


_FORTHCOMING = NseCurrentIssue(
    symbol="FUTUREMB",
    company="Future Mainboard Ltd",
    segment="mainboard",
    price_band_low=100.0,
    price_band_high=110.0,
    open_date=date(2026, 7, 20),
    close_date=date(2026, 7, 24),
)


def test_build_live_records_merges_forthcoming_from_upcoming() -> None:
    # a forthcoming issue (all-upcoming-issues) with a band joins the current-issue set
    recs = build_live_records(_client([_KNACK], upcoming=[_FORTHCOMING]))
    assert sorted(r.ipo_id for r in recs) == ["futuremb", "knack"]


def test_build_live_records_current_wins_over_upcoming_duplicate() -> None:
    stub_dupe = NseCurrentIssue(
        symbol="KNACK",
        company="Knack (forthcoming stub name)",
        segment="mainboard",
        price_band_low=161.0,
        price_band_high=170.0,
        open_date=date(2026, 7, 1),
        close_date=date(2026, 7, 3),
    )
    subs = {"KNACK": NseSubscription(qib=3.48, nii=19.22, retail=4.23, total=7.21)}
    recs = build_live_records(_client([_KNACK], subs, upcoming=[stub_dupe]))
    assert [r.ipo_id for r in recs] == ["knack"]  # deduped
    assert recs[0].name == "Knack Packaging Limited"  # current-issue entry won
    assert recs[0].qib_sub == 3.48  # …and carries its subscription


def test_refresh_upserts_and_counts() -> None:
    subs = {"KNACK": NseSubscription(qib=3.48, nii=19.22, retail=4.23, total=7.21)}
    repo = _Repo()
    n = refresh_from_nse(cast(Repository, repo), _client([_KNACK], subs))
    assert n == 1
    assert [r.ipo_id for r in repo.records] == ["knack"]


def test_refresh_never_raises_on_source_error() -> None:
    repo = _Repo()
    assert (
        refresh_from_nse(cast(Repository, repo), _client(None)) == 0
    )  # fetch failed → 0, no raise
    assert repo.records == []


# --- freshness state recording (v3 BUG 1 / Defect 2) --------------------------------------------

_INGEST_CLOCK = lambda: datetime(2026, 7, 14, 9, 0)  # noqa: E731


def test_refresh_records_success_freshness(tmp_path: object) -> None:
    from pathlib import Path

    from ipo.data.ingest.state import IngestStateStore

    subs = {"KNACK": NseSubscription(qib=3.48, nii=19.22, retail=4.23, total=7.21)}
    repo = _Repo()
    store = IngestStateStore(cast(Path, tmp_path) / "ingest_state.json")
    refresh_from_nse(
        cast(Repository, repo), _client([_KNACK], subs), clock=_INGEST_CLOCK, state=store
    )
    s = store.current()
    assert s.last_success == datetime(2026, 7, 14, 9, 0)  # a real pull advanced the honest clock
    assert s.last_attempt_ok is True


def test_refresh_failure_does_not_advance_success(tmp_path: object) -> None:
    from pathlib import Path

    from ipo.data.ingest.state import IngestStateStore

    store = IngestStateStore(cast(Path, tmp_path) / "ingest_state.json")
    store.record_success(datetime(2026, 7, 14, 6, 0))  # an earlier good pull
    repo = _Repo()
    # NSE unreachable this cycle → refresh degrades to 0 AND records the failure without lying
    n = refresh_from_nse(cast(Repository, repo), _client(None), clock=_INGEST_CLOCK, state=store)
    assert n == 0
    s = store.current()
    assert s.last_success == datetime(2026, 7, 14, 6, 0)  # unchanged — still honestly stale
    assert s.last_attempt == datetime(2026, 7, 14, 9, 0)  # the failed attempt is visible
    assert s.last_attempt_ok is False


def test_refresh_success_with_zero_records_is_still_fresh(tmp_path: object) -> None:
    """Reaching NSE and finding no active IPOs is a SUCCESSFUL pull — freshness advances."""
    from pathlib import Path

    from ipo.data.ingest.state import IngestStateStore

    store = IngestStateStore(cast(Path, tmp_path) / "ingest_state.json")
    repo = _Repo()
    n = refresh_from_nse(cast(Repository, repo), _client([]), clock=_INGEST_CLOCK, state=store)
    assert n == 0  # no records upserted…
    assert store.current().last_success == datetime(2026, 7, 14, 9, 0)  # …but NSE was reached


# --- listing resolution (Live → History lifecycle) ---------------------------------------------

_CLOCK = lambda: datetime(2026, 7, 10, 12, 0)  # noqa: E731 — 2026-07-10, a week after KNACK closed


def _require(repo: _Repo, ipo_id: str) -> IPORecord:
    """Fetch a record that must exist (narrows ``get``'s ``Optional`` for the assertions)."""
    r = repo.get(ipo_id)
    assert r is not None
    return r


def _awaiting_knack() -> IPORecord:
    """A stored KNACK record whose book has closed but which we haven't marked listed yet."""
    return IPORecord(
        ipo_id="knack",
        name="Knack Packaging Limited",
        segment=Segment("mainboard"),
        price_band_low=161.0,
        price_band_high=170.0,
        open_date=date(2026, 7, 1),
        close_date=date(2026, 7, 3),
        qib_sub=3.48,
        captured_at=datetime(2026, 7, 3, 17, 0),
    )


_KNACK_PAST = NsePastIssue(
    symbol="KNACK",
    company="Knack Packaging Limited",
    segment="mainboard",
    price_band_low=161.0,
    price_band_high=170.0,
    open_date=date(2026, 7, 1),
    close_date=date(2026, 7, 3),
    listing_date=date(2026, 7, 8),
)


def test_resolve_listings_marks_listed_with_prices() -> None:
    repo = _Repo([_awaiting_knack()])
    n = resolve_listings(
        cast(Repository, repo),
        _client(None, past=[_KNACK_PAST], prices={"KNACK": (175.0, 182.5)}),
        clock=_CLOCK,
    )
    assert n == 1
    r = repo.get("knack")
    assert r is not None
    assert r.listing_date == date(2026, 7, 8)  # now leaves Live, enters History
    assert (r.listing_open, r.listing_close) == (175.0, 182.5)


def test_resolve_listings_stamps_date_even_without_bhavcopy() -> None:
    repo = _Repo([_awaiting_knack()])
    n = resolve_listings(
        cast(Repository, repo),
        _client(None, past=[_KNACK_PAST], prices={"KNACK": None}),  # bhavcopy missing
        clock=_CLOCK,
    )
    assert n == 1
    r = repo.get("knack")
    assert r is not None
    assert r.listing_date == date(2026, 7, 8)  # still drops out of Live
    assert r.listing_open is None and r.listing_close is None


def test_resolve_listings_skips_not_yet_listed() -> None:
    future = NsePastIssue(
        symbol="KNACK",
        company="Knack Packaging Limited",
        segment="mainboard",
        price_band_low=161.0,
        price_band_high=170.0,
        open_date=date(2026, 7, 1),
        close_date=date(2026, 7, 3),
        listing_date=date(2026, 7, 15),  # in the future relative to the clock
    )
    repo = _Repo([_awaiting_knack()])
    n = resolve_listings(cast(Repository, repo), _client(None, past=[future]), clock=_CLOCK)
    assert n == 0
    assert _require(repo, "knack").listing_date is None  # untouched


def test_resolve_listings_ignores_open_and_fully_resolved() -> None:
    still_open = _awaiting_knack().model_copy(update={"close_date": date(2026, 7, 12)})  # book open
    done = _awaiting_knack().model_copy(  # already listed *with* prices → nothing to do
        update={
            "ipo_id": "done",
            "listing_date": date(2026, 7, 1),
            "listing_open": 200.0,
            "listing_close": 210.0,
        }
    )
    repo = _Repo([still_open, done])
    n = resolve_listings(
        cast(Repository, repo),
        _client(None, past=[_KNACK_PAST], prices={"KNACK": (175.0, 182.5)}),
        clock=_CLOCK,
    )
    assert n == 0


def test_resolve_listings_backfills_missing_price_after_stamp() -> None:
    """A row stamped listed but with no price (throttled bhavcopy) is retried and backfilled."""
    stamped_no_price = _awaiting_knack().model_copy(
        update={"listing_date": date(2026, 7, 8)}  # listed 2 days ago, price still missing
    )
    repo = _Repo([stamped_no_price])
    n = resolve_listings(
        cast(Repository, repo),
        _client(None, past=[_KNACK_PAST], prices={"KNACK": (175.0, 182.5)}),  # now available
        clock=_CLOCK,
    )
    assert n == 1
    r = _require(repo, "knack")
    assert (r.listing_open, r.listing_close) == (175.0, 182.5)
    assert r.listing_date == date(2026, 7, 8)  # unchanged


def test_resolve_listings_stops_backfilling_past_window() -> None:
    """Beyond the backfill window a still-priceless row is left alone (no perpetual re-fetch)."""
    old = _awaiting_knack().model_copy(
        update={"listing_date": date(2026, 6, 1)}  # >10 days before the clock
    )
    repo = _Repo([old])
    # a raising client proves past_issues isn't even fetched (row isn't a candidate)
    n = resolve_listings(cast(Repository, repo), _client(None, past=None), clock=_CLOCK)
    assert n == 0
    assert _require(repo, "knack").listing_open is None


def test_resolve_listings_never_raises_when_past_fetch_fails() -> None:
    repo = _Repo([_awaiting_knack()])
    assert resolve_listings(cast(Repository, repo), _client(None, past=None), clock=_CLOCK) == 0
    assert _require(repo, "knack").listing_date is None


def test_refresh_resolves_after_upsert() -> None:
    """End-to-end: a fresh current-issue upsert plus a separately-listed record both handled."""
    subs = {"KNACK": NseSubscription(qib=3.48, nii=19.22, retail=4.23, total=7.21)}
    other = _awaiting_knack().model_copy(
        update={"ipo_id": "oldco", "name": "Old Co"}  # closed earlier, now listed
    )
    old_past = NsePastIssue(
        symbol="OLDCO",
        company="Old Co",
        segment="mainboard",
        price_band_low=161.0,
        price_band_high=170.0,
        open_date=date(2026, 7, 1),
        close_date=date(2026, 7, 3),
        listing_date=date(2026, 7, 8),
    )
    repo = _Repo([other])
    n = refresh_from_nse(
        cast(Repository, repo),
        _client([_KNACK], subs, past=[old_past], prices={"OLDCO": (200.0, 210.0)}),
        clock=_CLOCK,
    )
    assert n == 1  # one current issue ingested
    assert repo.get("knack") is not None  # live upsert
    resolved = repo.get("oldco")
    assert resolved is not None and resolved.listing_date == date(2026, 7, 8)  # lifecycle completed
