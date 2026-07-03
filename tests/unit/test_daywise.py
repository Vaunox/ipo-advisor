"""Day-wise subscription recorder + append-only bank (v2 A1).

Covers GATE A1 end to end, offline: rows land append-only and timestamped for an open book;
a re-run duplicates nothing (content-dedupe on NSE's ``updateTime``); and a completed IPO's
reconstructed curve matches the observed progression. Also unit-tests the store's idempotency
and the NSE ``subscription_snapshot`` provenance assembly.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from ipo.core.constants import IST
from ipo.core.types import DaywiseSubscriptionRow, RawResponse
from ipo.data.ingest.daywise import record_daywise_subscription
from ipo.data.sources.base import PoliteClient, RawCache, SourceError, compute_hash
from ipo.data.sources.nse import (
    NseClient,
    NseCurrentIssue,
    NseSubscription,
    NseSubscriptionSnapshot,
    parse_subscription,
    parse_subscription_update_time,
)
from ipo.data.store.daywise import DaywiseSubscriptionStore

_FIX = Path(__file__).resolve().parents[1] / "fixtures"


# --- helpers ------------------------------------------------------------------


def _row(ipo_id: str, captured_at: datetime, **overrides: object) -> DaywiseSubscriptionRow:
    kwargs: dict[str, object] = dict(
        ipo_id=ipo_id,
        symbol=ipo_id.upper(),
        captured_at=captured_at,
        qib_sub=10.0,
        raw_response_hash="h",
    )
    kwargs.update(overrides)
    return DaywiseSubscriptionRow(**kwargs)  # type: ignore[arg-type]


def _snap(
    *,
    qib: float | None = None,
    nii: float | None = None,
    snii: float | None = None,
    bnii: float | None = None,
    retail: float | None = None,
    total: float | None = None,
    upd: str | None,
    h: str = "hash",
) -> NseSubscriptionSnapshot:
    return NseSubscriptionSnapshot(
        subscription=NseSubscription(
            qib=qib, nii=nii, retail=retail, total=total, nii_small=snii, nii_big=bnii
        ),
        source_update_time=upd,
        raw_hash=h,
    )


_OPEN_MB = NseCurrentIssue(
    symbol="KNACK",
    company="Knack Packaging Limited",
    segment="mainboard",
    price_band_low=161.0,
    price_band_high=170.0,
    open_date=date(2026, 7, 1),
    close_date=date(2026, 7, 3),
)


def _raw(content: str) -> RawResponse:
    return RawResponse(
        source="nse",
        url="https://www.nseindia.com/api/ipo-active-category?symbol=X",
        fetched_at=datetime(2026, 7, 2, tzinfo=IST),
        content=content,
        content_hash=compute_hash(content),
    )


def _advancing_clock(
    start: datetime, step: timedelta = timedelta(minutes=1)
) -> Callable[[], datetime]:
    """A clock that advances ``step`` each call — gives strictly-increasing poll times."""
    state = {"t": start}

    def _clock() -> datetime:
        state["t"] = state["t"] + step
        return state["t"]

    return _clock


class _StubClient:
    """Duck-typed NseClient: canned current issues + a per-symbol queue of snapshots."""

    def __init__(
        self,
        issues: list[NseCurrentIssue] | None,
        snapshots: dict[str, list[NseSubscriptionSnapshot | Exception]] | None = None,
    ) -> None:
        self._issues = issues
        self._snapshots = snapshots or {}

    def current_issues(self) -> list[NseCurrentIssue]:
        if self._issues is None:
            raise SourceError("nse unreachable")
        return self._issues

    def subscription_snapshot(self, symbol: str, *, force: bool = True) -> NseSubscriptionSnapshot:
        queue = self._snapshots.get(symbol)
        if not queue:
            raise SourceError(f"no snapshot for {symbol}")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _client(
    issues: list[NseCurrentIssue] | None,
    snapshots: dict[str, list[NseSubscriptionSnapshot | Exception]] | None = None,
) -> NseClient:
    return cast(NseClient, _StubClient(issues, snapshots))


# --- NSE snapshot provenance --------------------------------------------------


def test_parse_subscription_update_time_from_fixtures() -> None:
    for name, expected in (
        ("nse_active_category_sample.json", "Updated as on 02-Jul-2026 17:03:00"),
        ("nse_subscription_tatatech.json", "Updated as on 24-Nov-2023 19:00:00"),
    ):
        raw = _raw((_FIX / name).read_text(encoding="utf-8"))
        assert parse_subscription_update_time(raw) == expected
        # the multiples parser is unaffected by also reading updateTime
        assert parse_subscription(raw).qib is not None


def test_parse_subscription_update_time_absent_or_bad() -> None:
    assert parse_subscription_update_time(_raw('{"dataList": []}')) is None
    assert parse_subscription_update_time(_raw("[]")) is None  # not a dict
    with pytest.raises(SourceError):
        parse_subscription_update_time(_raw("not json"))


class _FakeResponse:
    def __init__(self, text: str, url: str) -> None:
        self.text = text
        self.url = url

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    def __init__(self, texts: list[str]) -> None:
        self._texts = texts
        self.calls = 0

    def get(self, url: str, params=None, headers=None, timeout=None):  # type: ignore[no-untyped-def]
        text = self._texts[self.calls]
        self.calls += 1
        return _FakeResponse(text, url=url)


def test_subscription_snapshot_assembles_provenance_via_live_fetch(tmp_path: Path) -> None:
    body = (_FIX / "nse_active_category_sample.json").read_text(encoding="utf-8")
    session = _FakeSession(["<html>cookie prime</html>", body])
    polite = PoliteClient(
        user_agent="test",
        rate_limit_per_sec=0,
        respect_robots=False,
        session=session,  # type: ignore[arg-type]
        sleep=lambda _s: None,
    )
    nse = NseClient(polite, RawCache(root=tmp_path))

    snap = nse.subscription_snapshot("KNACK")

    assert snap.subscription.qib == pytest.approx(3.4772, abs=1e-3)
    assert snap.subscription.nii_small == pytest.approx(17.1256, abs=1e-3)
    assert snap.source_update_time == "Updated as on 02-Jul-2026 17:03:00"
    assert snap.raw_hash == compute_hash(body)
    assert session.calls == 2  # cookie prime + one live (uncached) subscription fetch


# --- append-only store --------------------------------------------------------


def test_store_append_roundtrips_across_reopen(tmp_path: Path) -> None:
    store = DaywiseSubscriptionStore(tmp_path)
    at = datetime(2026, 7, 2, 11, 0, tzinfo=IST)
    assert store.append(_row("knack", at, qib_sub=40.0, source_update_time="u1")) is True

    reopened = DaywiseSubscriptionStore(tmp_path)
    rows = reopened.rows_for("knack")
    assert len(rows) == 1
    assert rows[0].qib_sub == 40.0
    assert rows[0].source_update_time == "u1"
    assert rows[0].captured_at == at


def test_store_append_idempotent_on_natural_key(tmp_path: Path) -> None:
    store = DaywiseSubscriptionStore(tmp_path)
    at = datetime(2026, 7, 2, 11, 0, tzinfo=IST)
    assert store.append(_row("knack", at, qib_sub=40.0)) is True
    # Same (ipo_id, captured_at) → append-only no-op; never overwrites the first observation.
    assert store.append(_row("knack", at, qib_sub=999.0)) is False
    rows = store.rows_for("knack")
    assert len(rows) == 1
    assert rows[0].qib_sub == 40.0  # original stands


def test_store_distinct_captures_accumulate_and_sort(tmp_path: Path) -> None:
    store = DaywiseSubscriptionStore(tmp_path)
    t1 = datetime(2026, 7, 2, 10, 0, tzinfo=IST)
    t2 = datetime(2026, 7, 2, 15, 0, tzinfo=IST)
    store.append(_row("knack", t2, qib_sub=40.0))
    store.append(_row("knack", t1, qib_sub=5.0))  # inserted out of order
    rows = store.rows_for("knack")
    assert [r.qib_sub for r in rows] == [5.0, 40.0]  # sorted by captured_at
    latest = store.latest_for("knack")
    assert latest is not None and latest.qib_sub == 40.0
    assert store.latest_for("absent") is None


# --- recorder -----------------------------------------------------------------


def test_records_open_mainboard_only(tmp_path: Path) -> None:
    sme = NseCurrentIssue(
        symbol="ICELCO",
        company="IC Electricals",
        segment="sme",
        price_band_low=50.0,
        price_band_high=55.0,
        open_date=date(2026, 7, 1),
        close_date=date(2026, 7, 3),
    )
    not_open = NseCurrentIssue(
        symbol="LATER",
        company="Later Ltd",
        segment="mainboard",
        price_band_low=100.0,
        price_band_high=110.0,
        open_date=date(2026, 7, 5),  # opens after the clock date
        close_date=date(2026, 7, 7),
    )
    store = DaywiseSubscriptionStore(tmp_path)
    snaps: dict[str, list[NseSubscriptionSnapshot | Exception]] = {
        "KNACK": [_snap(qib=40.0, upd="u1")],
        "ICELCO": [_snap(qib=99.0, upd="s1")],
        "LATER": [_snap(qib=1.0, upd="l1")],
    }
    n = record_daywise_subscription(
        store,
        _client([_OPEN_MB, sme, not_open], snaps),
        clock=_advancing_clock(datetime(2026, 7, 2, 10, 0, tzinfo=IST)),
    )
    assert n == 1
    assert {r.ipo_id for r in store.all_rows()} == {"knack"}  # SME + not-yet-open excluded


def test_rerun_produces_no_duplicates(tmp_path: Path) -> None:
    """GATE A1: polling again with an unchanged NSE snapshot banks nothing new."""
    store = DaywiseSubscriptionStore(tmp_path)
    stamp = "Updated as on 02-Jul-2026 17:03:00"  # same NSE publication on both polls
    snaps: dict[str, list[NseSubscriptionSnapshot | Exception]] = {
        "KNACK": [_snap(qib=40.0, total=7.2, upd=stamp), _snap(qib=40.0, total=7.2, upd=stamp)]
    }
    client = _client([_OPEN_MB, _OPEN_MB], snaps)  # issue list re-returned each pass
    clock = _advancing_clock(datetime(2026, 7, 2, 10, 0, tzinfo=IST), step=timedelta(hours=1))

    first = record_daywise_subscription(store, client, clock=clock)
    second = record_daywise_subscription(store, client, clock=clock)  # later poll, same figures

    assert (first, second) == (1, 0)
    assert len(store.rows_for("knack")) == 1  # no duplicate despite a new captured_at


def test_new_publication_appends_new_row(tmp_path: Path) -> None:
    """An advanced updateTime is a new publication and IS banked (even for the same number)."""
    store = DaywiseSubscriptionStore(tmp_path)
    snaps: dict[str, list[NseSubscriptionSnapshot | Exception]] = {
        "KNACK": [_snap(qib=40.0, upd="t1"), _snap(qib=40.0, upd="t2")]  # same qib, newer stamp
    }
    client = _client([_OPEN_MB, _OPEN_MB], snaps)
    clock = _advancing_clock(datetime(2026, 7, 2, 10, 0, tzinfo=IST), step=timedelta(hours=1))
    record_daywise_subscription(store, client, clock=clock)
    record_daywise_subscription(store, client, clock=clock)
    assert len(store.rows_for("knack")) == 2


def test_reconstructed_curve_matches_progression(tmp_path: Path) -> None:
    """GATE A1: banked rows reconstruct the observed subscription buildup in order."""
    store = DaywiseSubscriptionStore(tmp_path)
    observed = [
        _snap(qib=2.0, total=1.5, upd="t1"),
        _snap(qib=8.0, total=4.0, upd="t2"),
        _snap(qib=45.0, total=12.0, upd="t3"),  # final-day QIB surge
    ]
    snaps: dict[str, list[NseSubscriptionSnapshot | Exception]] = {"KNACK": list(observed)}
    client = _client([_OPEN_MB, _OPEN_MB, _OPEN_MB], snaps)
    clock = _advancing_clock(datetime(2026, 7, 2, 9, 0, tzinfo=IST), step=timedelta(hours=2))

    for _ in range(3):
        record_daywise_subscription(store, client, clock=clock)

    curve = store.rows_for("knack")
    assert [r.qib_sub for r in curve] == [2.0, 8.0, 45.0]  # ascending, in capture order
    assert [r.total_sub for r in curve] == [1.5, 4.0, 12.0]
    # captured_at strictly increasing (the load-bearing point-in-time anchor)
    assert curve[0].captured_at < curve[1].captured_at < curve[2].captured_at


def test_whole_fetch_failure_degrades_to_zero(tmp_path: Path) -> None:
    store = DaywiseSubscriptionStore(tmp_path)
    assert record_daywise_subscription(store, _client(None)) == 0  # current_issues raised
    assert store.all_rows() == []


def test_per_issue_failure_is_skipped(tmp_path: Path) -> None:
    other = NseCurrentIssue(
        symbol="GOODCO",
        company="Good Co",
        segment="mainboard",
        price_band_low=100.0,
        price_band_high=110.0,
        open_date=date(2026, 7, 1),
        close_date=date(2026, 7, 3),
    )
    store = DaywiseSubscriptionStore(tmp_path)
    snaps: dict[str, list[NseSubscriptionSnapshot | Exception]] = {
        "KNACK": [SourceError("throttled")],
        "GOODCO": [_snap(qib=12.0, upd="g1")],
    }
    n = record_daywise_subscription(
        store,
        _client([_OPEN_MB, other], snaps),
        clock=_advancing_clock(datetime(2026, 7, 2, 10, 0, tzinfo=IST)),
    )
    assert n == 1  # KNACK skipped, GOODCO recorded
    assert {r.ipo_id for r in store.all_rows()} == {"goodco"}


def test_empty_snapshot_not_banked(tmp_path: Path) -> None:
    store = DaywiseSubscriptionStore(tmp_path)
    snaps: dict[str, list[NseSubscriptionSnapshot | Exception]] = {
        "KNACK": [_snap(upd=None)]  # no stamp, no multiples → nothing worth banking
    }
    n = record_daywise_subscription(
        store,
        _client([_OPEN_MB], snaps),
        clock=_advancing_clock(datetime(2026, 7, 2, 10, 0, tzinfo=IST)),
    )
    assert n == 0
    assert store.all_rows() == []
