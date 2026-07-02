"""Live NSE ingestion — the orchestrator builds records from current issues, robustly, no network.

Uses a stub client (structurally an ``NseClient``) so the record-building and failure-handling
logic is deterministic and offline: mainboard-only, incomplete issues skipped, and a whole-fetch
failure degrades to zero records rather than raising (the sidecar must never crash on a hiccup).
"""

from __future__ import annotations

from datetime import date
from typing import cast

from ipo.core.interfaces import Repository
from ipo.core.types import IPORecord, ListingLabel
from ipo.data.ingest.live import build_live_records, refresh_from_nse
from ipo.data.sources.base import SourceError
from ipo.data.sources.nse import NseClient, NseCurrentIssue, NseSubscription


class _StubClient:
    """Duck-typed NseClient: returns canned current issues + subscription (or raises)."""

    def __init__(
        self, issues: list[NseCurrentIssue] | None, subs: dict[str, NseSubscription] | None = None
    ) -> None:
        self._issues = issues
        self._subs = subs or {}

    def current_issues(self) -> list[NseCurrentIssue]:
        if self._issues is None:
            raise SourceError("nse unreachable")
        return self._issues

    def subscription(self, symbol: str, *, force: bool = False) -> NseSubscription:
        return self._subs.get(symbol, NseSubscription(qib=None, nii=None, retail=None, total=None))


class _Repo:
    """Minimal in-memory Repository capturing upserts."""

    def __init__(self) -> None:
        self.records: list[IPORecord] = []

    def upsert(self, record: IPORecord) -> None:
        self.records.append(record)

    def upsert_many(self, records: list[IPORecord]) -> None:
        self.records.extend(records)

    def get(self, ipo_id: str) -> IPORecord | None:
        return None

    def list_all(self) -> list[IPORecord]:
        return list(self.records)

    def save_labels(self, labels: list[ListingLabel]) -> None: ...

    def load_labels(self) -> list[ListingLabel]:
        return []


def _client(
    issues: list[NseCurrentIssue] | None, subs: dict[str, NseSubscription] | None = None
) -> NseClient:
    return cast(NseClient, _StubClient(issues, subs))


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
