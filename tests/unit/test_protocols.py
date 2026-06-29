"""GATE 0: a fake of each Protocol type-checks (and satisfies runtime checks).

The variable annotations below (``ds: DataSource = ...``) make mypy verify that
each fake structurally conforms to its Protocol. The ``isinstance`` assertions
exercise the same conformance at runtime via ``@runtime_checkable``.

None of these contracts exposes an order-placement method — the system is
advisory only (Inviolable Rule 6).
"""

from __future__ import annotations

from datetime import datetime

from ipo.core.constants import IST
from ipo.core.interfaces import (
    Calibrator,
    DataSource,
    Notifier,
    Repository,
    ScoringModel,
)
from ipo.core.types import (
    IPOFeatures,
    IPORecord,
    ListingLabel,
    PartialRecord,
    RawResponse,
    Segment,
    Verdict,
    VerdictType,
)


class FakeDataSource:
    name = "fake"

    def fetch(self, ipo_id: str) -> RawResponse:
        return RawResponse(
            source=self.name,
            url="https://example.test",
            fetched_at=datetime(2026, 1, 1, tzinfo=IST),
            content="{}",
            content_hash="deadbeef",
        )

    def parse(self, raw: RawResponse) -> PartialRecord:
        return PartialRecord(source=raw.source, ipo_id="x", fields={})


class FakeRepository:
    def __init__(self) -> None:
        self._store: dict[str, IPORecord] = {}

        self._labels: list[ListingLabel] = []

    def upsert(self, record: IPORecord) -> None:
        self._store[record.ipo_id] = record

    def upsert_many(self, records: list[IPORecord]) -> None:
        for record in records:
            self._store[record.ipo_id] = record

    def get(self, ipo_id: str) -> IPORecord | None:
        return self._store.get(ipo_id)

    def list_all(self) -> list[IPORecord]:
        return list(self._store.values())

    def save_labels(self, labels: list[ListingLabel]) -> None:
        self._labels = list(labels)

    def load_labels(self) -> list[ListingLabel]:
        return list(self._labels)


class FakeScoringModel:
    def score(self, features: IPOFeatures) -> float:
        return 0.0

    def contributions(self, features: IPOFeatures) -> dict[str, float]:
        return {}


class FakeCalibrator:
    version = "fake-0"

    def fit(self, raw_scores: list[float], labels: list[int]) -> None:
        return None

    def predict_proba(self, raw_score: float) -> float:
        return 0.5

    @property
    def passes_reliability_gate(self) -> bool:
        return False


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def notify(self, verdict: Verdict, *, message: str) -> None:
        self.sent.append(message)


def test_fakes_conform_to_protocols() -> None:
    ds: DataSource = FakeDataSource()
    repo: Repository = FakeRepository()
    model: ScoringModel = FakeScoringModel()
    calib: Calibrator = FakeCalibrator()
    notifier: Notifier = FakeNotifier()

    assert isinstance(ds, DataSource)
    assert isinstance(repo, Repository)
    assert isinstance(model, ScoringModel)
    assert isinstance(calib, Calibrator)
    assert isinstance(notifier, Notifier)


def test_fake_repository_roundtrip() -> None:
    repo: Repository = FakeRepository()
    rec = IPORecord(
        ipo_id="demo",
        name="Demo Ltd",
        segment=Segment.MAINBOARD,
        price_band_low=90,
        price_band_high=100,
        lot_size=150,
        issue_size_cr=500,
        open_date=datetime(2026, 1, 1).date(),
        close_date=datetime(2026, 1, 3).date(),
        captured_at=datetime(2026, 1, 3, tzinfo=IST),
    )
    repo.upsert(rec)
    repo.upsert(rec)  # idempotent: still one row
    assert len(repo.list_all()) == 1
    assert repo.get("demo") == rec
    assert repo.get("missing") is None


def test_fake_notifier_receives_verdict() -> None:
    notifier: Notifier = FakeNotifier()
    verdict = Verdict(ipo_id="demo", verdict=VerdictType.APPLY, probability=0.72)
    notifier.notify(verdict, message="Demo -> APPLY, 72%")
    assert isinstance(notifier, FakeNotifier)
    assert notifier.sent == ["Demo -> APPLY, 72%"]
