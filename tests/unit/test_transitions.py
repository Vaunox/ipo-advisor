"""Phase 7: the durable verdict-transition log records real changes and never fabricates history.

* **Store round-trips.** Transitions persist to disk, reload, and read back most-recent-first;
  ``latest_by_ipo`` returns each IPO's newest verdict (used to prime the scheduler).
* **Scheduler logs genuine changes only.** A first observation that is merely abstaining
  (None -> INSUFFICIENT_SIGNAL) is not an event; a real resolution / crossing is logged once;
  the steady state logs nothing (the durable log inherits the no-duplicate guarantee).
* **Priming prevents duplicate history.** Seeded with the last-known verdict, a restart does not
  re-record what it already knows.
* **The API is a thin reader.** ``/transitions`` serves the log verbatim, name-joined, and
  ``/transitions/{id}`` filters to one IPO (404 if unknown) — no re-score.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from ipo.core.config import load_config
from ipo.core.constants import IST
from ipo.core.types import IPORecord, ListingLabel, Segment, Verdict, VerdictType
from ipo.model.calibrator_placeholder import PlaceholderCalibrator
from ipo.model.scorer import WeightedScorer
from ipo.service.api import create_app
from ipo.service.engine import VerdictEngine
from ipo.service.scheduler import ScoringScheduler
from ipo.service.transitions import TransitionStore, VerdictTransition

APPLY = VerdictType.APPLY
SKIP = VerdictType.SKIP
INSUFF = VerdictType.INSUFFICIENT_SIGNAL


def _dt(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, 18, tzinfo=IST)


def _t(
    ipo_id: str, when: datetime, frm: VerdictType | None, to: VerdictType, cross: bool
) -> VerdictTransition:
    return VerdictTransition(
        ipo_id=ipo_id,
        asof=when,
        from_verdict=frm,
        to_verdict=to,
        probability=None,
        crossed_into_apply=cross,
    )


class _ListRepo:
    """Minimal in-memory Repository over a fixed record list (the engine only reads it)."""

    def __init__(self, records: list[IPORecord]) -> None:
        self._records = records

    def upsert(self, record: IPORecord) -> None: ...

    def upsert_many(self, records: list[IPORecord]) -> None: ...

    def get(self, ipo_id: str) -> IPORecord | None:
        return next((r for r in self._records if r.ipo_id == ipo_id), None)

    def list_all(self) -> list[IPORecord]:
        return list(self._records)

    def save_labels(self, labels: list[ListingLabel]) -> None: ...

    def load_labels(self) -> list[ListingLabel]:
        return []


class _FakeSource:
    """A controllable VerdictSource: the scheduler reads whatever verdicts we set."""

    def __init__(self, verdicts: list[Verdict]) -> None:
        self.verdicts_to_return = verdicts

    def verdicts(self, *, asof: datetime | None = None) -> list[Verdict]:
        return list(self.verdicts_to_return)

    def records(self) -> list[IPORecord]:
        return []


def _record(ipo_id: str, name: str) -> IPORecord:
    return IPORecord(
        ipo_id=ipo_id,
        name=name,
        segment=Segment.MAINBOARD,
        price_band_low=90,
        price_band_high=100,
        open_date=date(2021, 7, 14),
        close_date=date(2021, 7, 16),
        listing_date=date(2021, 7, 23),
        captured_at=_dt(2021, 7, 16),
    )


def _engine(records: list[IPORecord], store: TransitionStore) -> VerdictEngine:
    config = load_config(env="dev", environ={})
    return VerdictEngine(
        repository=_ListRepo(records),
        calibrator=PlaceholderCalibrator(),
        scorer=WeightedScorer(config.feature_weights, config.features),
        config=config,
        transitions=store,
    )


# --- Store ------------------------------------------------------------------


def test_store_roundtrips_most_recent_first(tmp_path: Path) -> None:
    path = tmp_path / "transitions.json"
    store = TransitionStore(path)
    store.record(_t("a", _dt(2021, 1, 1), INSUFF, APPLY, True))
    store.record(_t("a", _dt(2021, 3, 1), APPLY, SKIP, False))
    store.record(_t("b", _dt(2021, 2, 1), INSUFF, SKIP, False))

    reloaded = TransitionStore(path)  # durable: reads back from disk
    ordered = reloaded.all()
    assert [t.asof for t in ordered] == sorted((t.asof for t in ordered), reverse=True)
    assert [(t.ipo_id, t.to_verdict) for t in ordered] == [("a", SKIP), ("b", SKIP), ("a", APPLY)]
    assert [t.ipo_id for t in reloaded.for_ipo("a")] == ["a", "a"]
    assert reloaded.latest_by_ipo() == {"a": SKIP, "b": SKIP}  # a's newest is 2021-03-01 SKIP


# --- Scheduler recording ----------------------------------------------------


def test_first_abstention_is_not_logged() -> None:
    config = load_config(env="dev", environ={})
    recorded: list[VerdictTransition] = []
    source = _FakeSource([Verdict(ipo_id="X", verdict=INSUFF)])
    scheduler = ScoringScheduler(source=source, config=config, on_transition=recorded.append)

    scheduler.run_cycle()
    assert recorded == []  # starting to watch an open book (None -> INSUFFICIENT) is not an event


def test_resolution_and_crossing_logged_once() -> None:
    config = load_config(env="dev", environ={})
    recorded: list[VerdictTransition] = []
    source = _FakeSource([Verdict(ipo_id="X", verdict=INSUFF)])
    scheduler = ScoringScheduler(source=source, config=config, on_transition=recorded.append)

    scheduler.run_cycle()  # abstaining -> nothing
    source.verdicts_to_return = [Verdict(ipo_id="X", verdict=APPLY, probability=0.8)]
    scheduler.run_cycle()  # INSUFFICIENT -> APPLY (a real resolution + crossing)
    scheduler.run_cycle()  # stays APPLY -> no duplicate

    assert len(recorded) == 1
    t = recorded[0]
    assert (t.from_verdict, t.to_verdict, t.crossed_into_apply) == (INSUFF, APPLY, True)
    assert t.probability == 0.8


def test_priming_prevents_rerecording_known_verdict() -> None:
    config = load_config(env="dev", environ={})
    recorded: list[VerdictTransition] = []
    source = _FakeSource([Verdict(ipo_id="X", verdict=APPLY, probability=0.8)])
    scheduler = ScoringScheduler(
        source=source, config=config, on_transition=recorded.append, initial_last={"X": APPLY}
    )

    result = scheduler.run_cycle()
    assert recorded == []  # already known APPLY -> no fresh transition on restart
    assert result.became_apply == []  # and not re-alerted as a new crossing


# --- Engine + API (thin reader) ---------------------------------------------


def test_api_serves_transitions_name_joined_and_filtered(tmp_path: Path) -> None:
    store = TransitionStore(tmp_path / "transitions.json")
    store.record(_t("zomato", _dt(2021, 7, 16), INSUFF, APPLY, True))
    store.record(_t("paytm", _dt(2021, 11, 10), INSUFF, SKIP, False))
    records = [_record("zomato", "Zomato Ltd"), _record("paytm", "One 97 (Paytm) Ltd")]
    client = TestClient(create_app(_engine(records, store)))

    rows = client.get("/transitions").json()
    assert [r["ipo_id"] for r in rows] == ["paytm", "zomato"]  # most-recent-first
    assert rows[1]["name"] == "Zomato Ltd"  # name joined from the record
    assert rows[1]["crossed_into_apply"] is True

    one = client.get("/transitions/zomato").json()
    assert [r["ipo_id"] for r in one] == ["zomato"]
    assert client.get("/transitions/unknown").status_code == 404


def test_transitions_empty_without_store() -> None:
    config = load_config(env="dev", environ={})
    engine = VerdictEngine(
        repository=_ListRepo([]),
        calibrator=PlaceholderCalibrator(),
        scorer=WeightedScorer(config.feature_weights, config.features),
        config=config,
    )
    assert TestClient(create_app(engine)).get("/transitions").json() == []
