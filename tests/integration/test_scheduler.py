"""Phase 6 step 4: the scheduler's cycles are idempotent, transition-aware, and as-of now.

* **Idempotent** — a second cycle over unchanged state returns identical verdicts and no
  repeated APPLY crossings (no duplicate notifications).
* **Transition fires once** — a crossing INTO APPLY is emitted on the crossing cycle only;
  staying APPLY emits nothing.
* **Windowed cadence** — 30 min while a book is open, the default otherwise.
* **As-of now** — a scheduled run uses only data dated at/before its clock; appending future
  Nifty closes cannot change the cycle's verdicts (no look-ahead leak).
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import pytest

from ipo.calibration.calibrate import load_calibrator
from ipo.calibration.dataset import load_records_from_csv
from ipo.calibration.regime import NiftyRegime
from ipo.core.calendar import now_ist
from ipo.core.config import AppConfig, load_config
from ipo.core.constants import IST
from ipo.core.types import IPORecord, ListingLabel, Segment, Verdict, VerdictType
from ipo.model.scorer import WeightedScorer
from ipo.service.engine import VerdictEngine
from ipo.service.scheduler import ScoringScheduler

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CSV = _REPO_ROOT / "data" / "backfill" / "mainboard_ipos.csv"
_NIFTY = _REPO_ROOT / "data" / "backfill" / "nifty.csv"
_CAL = _REPO_ROOT / "models" / "calibrator.json"

pytestmark = pytest.mark.skipif(
    not (_CSV.is_file() and _NIFTY.is_file() and _CAL.is_file()),
    reason="backfill / calibrator artifacts not present",
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
    """A controllable VerdictSource for the transition / cadence tests."""

    def __init__(self, verdicts: list[Verdict], records: list[IPORecord] | None = None) -> None:
        self.verdicts_to_return = verdicts
        self.records_to_return = records or []

    def verdicts(self, *, asof: datetime | None = None) -> list[Verdict]:
        return list(self.verdicts_to_return)

    def records(self) -> list[IPORecord]:
        return list(self.records_to_return)


def _record(*, open_d: date, close_d: date) -> IPORecord:
    return IPORecord(
        ipo_id=f"T-{close_d.isoformat()}",
        name="Test Co",
        segment=Segment.MAINBOARD,
        price_band_low=90,
        price_band_high=100,
        lot_size=150,
        issue_size_cr=500,
        open_date=open_d,
        close_date=close_d,
        captured_at=datetime(close_d.year, close_d.month, close_d.day, tzinfo=IST),
    )


def _engine(
    nifty: Path, clock: Callable[[], datetime] = now_ist
) -> tuple[VerdictEngine, AppConfig]:
    config = load_config(env="dev", environ={})
    records = load_records_from_csv(_CSV)
    engine = VerdictEngine(
        repository=_ListRepo(records),
        calibrator=load_calibrator(_CAL),
        scorer=WeightedScorer(config.feature_weights, config.features),
        config=config,
        regime=NiftyRegime(nifty),
        clock=clock,
    )
    return engine, config


def _tuples(verdicts: list[Verdict]) -> list[tuple[str, VerdictType, float | None]]:
    return [(v.ipo_id, v.verdict, v.probability) for v in verdicts]


def _write_nifty_upto(src: Path, dst: Path, cutoff: date) -> None:
    with src.open(encoding="utf-8") as handle, dst.open("w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        writer.writerow(["date", "close"])
        for row in csv.DictReader(handle):
            if date.fromisoformat(row["date"]) <= cutoff:
                writer.writerow([row["date"], row["close"]])


def test_cycle_is_idempotent() -> None:
    engine, config = _engine(_NIFTY)
    scheduler = ScoringScheduler(source=engine, config=config)

    first = scheduler.run_cycle()
    second = scheduler.run_cycle()

    assert _tuples(first.verdicts) == _tuples(second.verdicts)  # identical results
    expected = [v.ipo_id for v in first.verdicts if v.verdict is VerdictType.APPLY]
    assert len(expected) > 0  # the backfill does contain APPLYs (the test is non-vacuous)
    assert first.became_apply == expected  # cycle 1 reports the current APPLYs once
    assert second.became_apply == []  # cycle 2 over the same state: no duplicate notifications


def test_apply_transition_fires_once() -> None:
    config = load_config(env="dev", environ={})
    source = _FakeSource([Verdict(ipo_id="X", verdict=VerdictType.SKIP)])
    scheduler = ScoringScheduler(source=source, config=config)

    assert scheduler.run_cycle().became_apply == []  # starts SKIP
    source.verdicts_to_return = [Verdict(ipo_id="X", verdict=VerdictType.APPLY, probability=0.8)]
    assert scheduler.run_cycle().became_apply == ["X"]  # crosses INTO APPLY -> fires once
    assert scheduler.run_cycle().became_apply == []  # stays APPLY -> no re-alert


def test_cadence_is_windowed() -> None:
    config = load_config(env="dev", environ={})
    clock = lambda: datetime(2026, 6, 15, 12, tzinfo=IST)  # noqa: E731
    open_book = _FakeSource([], [_record(open_d=date(2026, 6, 14), close_d=date(2026, 6, 17))])
    no_book = _FakeSource([], [_record(open_d=date(2026, 1, 1), close_d=date(2026, 1, 3))])

    sched_open = ScoringScheduler(source=open_book, config=config, clock=clock)
    sched_closed = ScoringScheduler(source=no_book, config=config, clock=clock)

    assert sched_open.next_cadence_minutes() == config.scrape.cadence_minutes_subscription_window
    assert sched_closed.next_cadence_minutes() == config.scrape.cadence_minutes_default


def test_scheduled_run_is_as_of_now(tmp_path: Path) -> None:
    asof = datetime(2023, 6, 1, 18, tzinfo=IST)
    truncated = tmp_path / "nifty_upto_T.csv"
    _write_nifty_upto(_NIFTY, truncated, asof.date())

    engine_full, config = _engine(_NIFTY, clock=lambda: asof)
    engine_trunc, _ = _engine(truncated, clock=lambda: asof)
    sched_full = ScoringScheduler(source=engine_full, config=config, clock=lambda: asof)
    sched_trunc = ScoringScheduler(source=engine_trunc, config=config, clock=lambda: asof)

    # Identical verdicts whether or not Nifty has data after the cycle's clock -> no future leak.
    assert _tuples(sched_full.run_cycle().verdicts) == _tuples(sched_trunc.run_cycle().verdicts)
