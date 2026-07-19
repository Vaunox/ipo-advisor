"""DP-1 forward subscription recorder (v3-DP) — the invariants, proven rather than asserted.

The four claims this file exists to hold down, in the order they'd hurt if they broke:

1. **A torn write cannot corrupt the accumulated series** (the review's #2/#3 criticals).
2. **A failed fetch banks NOTHING** — never a fabricated row replayed from the prior record.
3. **A recorder fault cannot break ingest** — it degrades to a gap, never to a missed score.
4. **Append-only holds** — never overwrite an observation, never shrink the series.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from ipo.core.constants import IST
from ipo.core.types import IPORecord, RawResponse, Segment
from ipo.data.ingest.live import build_live_records
from ipo.data.sources.base import SourceError
from ipo.data.sources.nse import (
    NseClient,
    NseCurrentIssue,
    NseSubscriptionSnapshot,
    parse_subscription,
)
from ipo.series.models import SubscriptionSample
from ipo.series.recorder import SeriesSink, build_sample, in_recording_window
from ipo.series.state import RecorderStateStore
from ipo.series.store import SeriesWriteError, SubscriptionSeriesStore

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "nse_active_category_sample.json"
_RAW = _FIXTURE.read_bytes()
_NOW = datetime(2026, 7, 2, 14, 0, tzinfo=IST)


def _raw() -> RawResponse:
    return RawResponse(
        source="nse",
        url="https://example/ipo-active-category?symbol=ACME",
        fetched_at=_NOW,
        content=_RAW.decode("utf-8"),
        content_hash="h",
    )


def _sample(captured_at: datetime, ipo_id: str = "acme") -> SubscriptionSample:
    return build_sample(
        ipo_id=ipo_id, symbol=ipo_id.upper(), captured_at=captured_at, raw_content=_RAW
    )


# --- the store: durability + append-only ------------------------------------


def test_torn_write_cannot_corrupt_the_accumulated_series(tmp_path: Path) -> None:
    """THE headline durability claim: an interrupted write leaves the bank intact.

    Simulates the crash window precisely — the tmp file is written (possibly garbage, possibly
    half a document) but ``os.replace`` never runs. With tmp+replace there is no interleaving
    observable at the live path, so the previously-banked series must read back COMPLETE.
    """
    store = SubscriptionSeriesStore(tmp_path)
    banked = [_sample(_NOW), _sample(_NOW + timedelta(minutes=30))]
    store.append_many("acme", banked)
    assert len(store.read("acme")) == 2

    path = store.path_for("acme")
    intact = path.read_bytes()

    # A crash after the tmp write but before the atomic swap.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(b'[{"ipo_id": "acme", "captured_at": "2026-07-02T15:0')  # truncated JSON

    assert path.read_bytes() == intact, "the live file was touched before the atomic swap"
    assert len(store.read("acme")) == 2, "a torn tmp write must not affect the banked series"

    # And the store recovers normally on the next cycle.
    assert store.append_many("acme", [_sample(_NOW + timedelta(minutes=60))]) == 1
    assert len(store.read("acme")) == 3


def test_write_is_atomic_no_partial_file_is_ever_observable(tmp_path: Path) -> None:
    """``os.replace`` is the mechanism; assert the write really goes through tmp, not in place."""
    store = SubscriptionSeriesStore(tmp_path)
    path = store.path_for("acme")
    seen: list[bool] = []
    real_replace = os.replace

    def spy(src: Any, dst: Any) -> None:
        # At the moment of the swap the destination must still hold the PREVIOUS complete state.
        seen.append(Path(str(dst)).exists())
        real_replace(src, dst)

    store.append_many("acme", [_sample(_NOW)])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "replace", spy)
        store.append_many("acme", [_sample(_NOW + timedelta(minutes=30))])
    assert seen == [True], "the swap did not go through os.replace onto an existing file"
    assert len(store.read("acme")) == 2
    assert not path.with_suffix(path.suffix + ".tmp").exists(), "tmp file left behind"


def test_never_overwrites_an_existing_observation(tmp_path: Path) -> None:
    """An observation at an instant is immutable; re-appending it is an idempotent no-op."""
    store = SubscriptionSeriesStore(tmp_path)
    assert store.append_many("acme", [_sample(_NOW)]) == 1
    assert store.append_many("acme", [_sample(_NOW)]) == 0  # same (ipo_id, captured_at)
    assert len(store.read("acme")) == 1


def test_never_shrink_guard_refuses_and_writes_nothing(tmp_path: Path) -> None:
    """NON-VACUOUS: force a shrink and prove the guard fires AND leaves the bank untouched.

    The guard cannot trigger through the normal add-only path, which is exactly why it needs a
    test that actually attempts the shrink — otherwise it is a comment that happens to compile.
    """
    store = SubscriptionSeriesStore(tmp_path)
    store.append_many("acme", [_sample(_NOW), _sample(_NOW + timedelta(minutes=30))])
    before = store.path_for("acme").read_bytes()

    # Simulate a future refactor that starts pruning inside the merge seam.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(SubscriptionSeriesStore, "_merge", lambda self, by_key: [])
        with pytest.raises(SeriesWriteError, match="refusing to shrink"):
            store.append_many("acme", [_sample(_NOW + timedelta(minutes=60))])

    assert store.path_for("acme").read_bytes() == before, "a refused write still modified the file"


def test_corrupt_existing_series_refuses_the_write_rather_than_clobbering(tmp_path: Path) -> None:
    """An unreadable file must NOT be replaced by a fresh one-row file — that destroys the bank."""
    store = SubscriptionSeriesStore(tmp_path)
    store.append_many("acme", [_sample(_NOW)])
    store.path_for("acme").write_text("{ not json", encoding="utf-8")

    with pytest.raises(SeriesWriteError, match="unreadable"):
        store.append_many("acme", [_sample(_NOW + timedelta(minutes=30))])
    assert store.path_for("acme").read_text(encoding="utf-8") == "{ not json"


def test_read_degrades_honestly_for_absent_and_corrupt(tmp_path: Path) -> None:
    """DP-2's months-long common case: no series is 'not recorded', never an error."""
    store = SubscriptionSeriesStore(tmp_path)
    assert store.read("never-heard-of-it") == []
    store.append_many("acme", [_sample(_NOW)])
    store.path_for("acme").write_text("[[[", encoding="utf-8")
    assert store.read("acme") == []  # logged, not raised


def test_one_ipos_corruption_cannot_reach_another(tmp_path: Path) -> None:
    """Per-IPO files bound the blast radius — the whole point of the layout."""
    store = SubscriptionSeriesStore(tmp_path)
    store.append_many("acme", [_sample(_NOW, "acme")])
    store.append_many("brava", [_sample(_NOW, "brava")])
    store.path_for("acme").write_text("corrupt", encoding="utf-8")
    assert store.read("acme") == []
    assert len(store.read("brava")) == 1


def test_unsafe_ipo_id_is_refused_not_sanitised(tmp_path: Path) -> None:
    """Sanitising two different ids into one filename would silently merge two IPOs' series."""
    store = SubscriptionSeriesStore(tmp_path)
    for bad in ("../escape", "a/b", ""):
        with pytest.raises(SeriesWriteError):
            store.path_for(bad)


# --- the sample: everything NSE returns, nothing invented -------------------


def test_sample_captures_the_whole_book_and_nses_own_stamp() -> None:
    sample = _sample(_NOW)
    assert sample.source_update_time == "Updated as on 02-Jul-2026 17:03:00"  # verbatim
    assert sample.source_update_time_parsed == datetime(2026, 7, 2, 17, 3, 0)
    # Every category NSE returned, minus the header row — and the raw counts behind the multiples.
    assert len(sample.categories) == 21
    assert all(c.category.lower() != "category" for c in sample.categories)
    assert any(c.no_of_shares_offered is not None for c in sample.categories)
    assert any(c.no_of_shares_bid is not None for c in sample.categories)
    # The complete response is retained directly-loadable, not as an escaped string.
    assert isinstance(sample.raw_response, dict)
    assert sample.raw_response["updateTime"] == "Updated as on 02-Jul-2026 17:03:00"
    assert len(sample.raw_response_hash) == 64


def test_banked_headline_multiples_match_the_scoring_paths_parse() -> None:
    """The series and the scorer must never disagree about what 'QIB' means."""
    scored = parse_subscription(_raw())
    banked = _sample(_NOW)
    assert banked.qib_sub == scored.qib
    assert banked.nii_sub == scored.nii
    assert banked.retail_sub == scored.retail
    assert banked.total_sub == scored.total
    assert banked.snii_sub == scored.nii_small
    assert banked.bnii_sub == scored.nii_big


# --- the window gate --------------------------------------------------------


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 6, 30), False),  # before open — there is no book
        (date(2026, 7, 1), True),  # open day
        (date(2026, 7, 2), True),  # mid-window
        (date(2026, 7, 3), True),  # close day INCLUSIVE — the surge the study needs
        (date(2026, 7, 4), False),  # after close — settled
    ],
)
def test_recording_window_is_open_through_close_inclusive(today: date, expected: bool) -> None:
    assert in_recording_window(date(2026, 7, 1), date(2026, 7, 3), today) is expected


def test_sink_counts_in_window_only(tmp_path: Path) -> None:
    """`in_window` drives the 'idle vs broken' health distinction, so it must count honestly."""
    sink = SeriesSink()
    # Not yet open -> neither counted nor banked.
    assert not sink.observe(
        ipo_id="acme",
        symbol="ACME",
        captured_at=_NOW,
        raw_content=_RAW,
        open_date=date(2026, 8, 1),
        close_date=date(2026, 8, 3),
        today=date(2026, 7, 2),
    )
    assert sink.in_window == 0 and sink.samples == []
    # Inside the window -> counted and banked.
    assert sink.observe(
        ipo_id="acme",
        symbol="ACME",
        captured_at=_NOW,
        raw_content=_RAW,
        open_date=date(2026, 7, 1),
        close_date=date(2026, 7, 3),
        today=date(2026, 7, 2),
    )
    assert sink.in_window == 1 and len(sink.samples) == 1


def test_flat_reading_is_recorded_not_deduped(tmp_path: Path) -> None:
    """A flat stretch is SIGNAL ('the book did not move'), so identical readings still bank.

    The retired v2-A1 recorder deduped on the NSE stamp; DP-1 deliberately does not — de-duping
    would discard the exact 'no surge happened' evidence the close-day question needs.
    """
    store = SubscriptionSeriesStore(tmp_path)
    first, second = _sample(_NOW), _sample(_NOW + timedelta(minutes=30))
    assert first.raw_response_hash == second.raw_response_hash  # byte-identical book
    assert first.source_update_time == second.source_update_time  # NSE didn't move either
    store.append_many("acme", [first, second])
    assert len(store.read("acme")) == 2, "an unchanged reading must still be banked"


# --- the fabricated-row hazard + ingest isolation ---------------------------


class _Issue:
    """Minimal NSE client double driving build_live_records through both fork branches."""

    def __init__(self, *, fail: bool) -> None:
        self._fail = fail
        self.issue = NseCurrentIssue(
            symbol="ACME",
            company="Acme Ltd",
            segment="mainboard",
            price_band_low=100.0,
            price_band_high=110.0,
            open_date=date(2026, 7, 1),
            close_date=date(2026, 7, 3),
        )

    def current_issues(self) -> list[NseCurrentIssue]:
        return [self.issue]

    def upcoming_issues(self) -> list[NseCurrentIssue]:
        return []

    def subscription_snapshot(self, symbol: str, *, force: bool = False) -> object:
        if self._fail:
            raise SourceError("nse: boom")
        return NseSubscriptionSnapshot(
            subscription=parse_subscription(_raw()),
            raw_content=_RAW,
            update_time="Updated as on 02-Jul-2026 17:03:00",
        )


def test_failed_fetch_banks_nothing_no_fabricated_row() -> None:
    """A degraded/preserved reading must be STRUCTURALLY unable to reach the series.

    ``_degrade_subscription`` replays the PRIOR record's numbers stamped with the PRIOR
    ``captured_at``. Banking that would write a sample indistinguishable, after the fact, from a
    genuine one — in a store whose entire value is being trustworthy months from now. An honest
    gap is the correct output.
    """
    prior = IPORecord(
        ipo_id="acme",
        name="Acme Ltd",
        segment=Segment("mainboard"),
        price_band_low=100.0,
        price_band_high=110.0,
        open_date=date(2026, 7, 1),
        close_date=date(2026, 7, 3),
        qib_sub=42.0,
        captured_at=_NOW - timedelta(hours=3),
    )
    sink = SeriesSink()
    records = build_live_records(
        cast(NseClient, _Issue(fail=True)), clock=lambda: _NOW, existing={"acme": prior}, sink=sink
    )
    # The scoring path still preserved the book (that behaviour is unchanged) ...
    assert records and records[0].qib_sub == 42.0
    # ... but the series banked NOTHING.
    assert sink.samples == []
    assert sink.in_window == 0


def test_successful_fetch_banks_exactly_one_sample() -> None:
    sink = SeriesSink()
    records = build_live_records(cast(NseClient, _Issue(fail=False)), clock=lambda: _NOW, sink=sink)
    assert len(records) == 1
    assert len(sink.samples) == 1
    assert sink.samples[0].ipo_id == "acme"
    assert sink.samples[0].captured_at == _NOW


def test_a_broken_recorder_cannot_break_ingest() -> None:
    """Claim 3, proven: the recorder explodes, ingest still produces its scoring records."""

    class Exploding(SeriesSink):
        def observe(self, **kwargs: object) -> bool:
            raise RuntimeError("recorder is on fire")

    records = build_live_records(
        cast(NseClient, _Issue(fail=False)), clock=lambda: _NOW, sink=Exploding()
    )
    assert len(records) == 1, "a recorder fault cost us a scoring record"
    assert records[0].qib_sub is not None


def test_no_sink_behaves_exactly_as_before() -> None:
    """The desktop path passes no sink; that must be byte-identical to pre-DP-1 behaviour."""
    with_sink = build_live_records(
        cast(NseClient, _Issue(fail=False)), clock=lambda: _NOW, sink=SeriesSink()
    )
    without = build_live_records(cast(NseClient, _Issue(fail=False)), clock=lambda: _NOW)
    assert [r.model_dump() for r in with_sink] == [r.model_dump() for r in without]


# --- recorder state (the health surface's input) ----------------------------


def test_recorder_state_distinguishes_idle_from_written(tmp_path: Path) -> None:
    store = RecorderStateStore(tmp_path)
    idle = store.record_cycle(now=_NOW, in_window=0, written=0)
    assert idle.last_write_at is None and idle.samples_total == 0

    wrote = store.record_cycle(now=_NOW + timedelta(minutes=30), in_window=2, written=2)
    assert wrote.last_write_at == _NOW + timedelta(minutes=30)
    assert wrote.samples_total == 2

    # A later idle cycle must NOT advance last_write_at — a quiet cycle is not a write.
    later = store.record_cycle(now=_NOW + timedelta(minutes=60), in_window=0, written=0)
    assert later.last_write_at == _NOW + timedelta(minutes=30)
    assert later.samples_total == 2


def test_recorder_state_survives_a_corrupt_file(tmp_path: Path) -> None:
    store = RecorderStateStore(tmp_path)
    store.record_cycle(now=_NOW, in_window=1, written=1)
    store.path.write_text("{{{", encoding="utf-8")
    assert store.read().last_cycle_at is None  # honest "never run", not a crash


def test_recorder_state_file_is_json_and_atomic(tmp_path: Path) -> None:
    store = RecorderStateStore(tmp_path)
    store.record_cycle(now=_NOW, in_window=1, written=1, error="acme: nope")
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["last_error"] == "acme: nope"
    assert not store.path.with_suffix(store.path.suffix + ".tmp").exists()
