"""GATE 6 — the five invariants survive being wired together end-to-end (Phase 6 capstone).

This is a composition gate, not a smoke test. Each function proves one invariant on the fully
composed ``Service`` (engine + scheduler + notifier + API):

1. End-to-end happy path: ingest → score → serve over API → fire on APPLY crossing, windowed.
2. Calibration-sacred: the cold flag fires through the running service, yet the probability is
   byte-identical to the official-only path (step-1 guarantee, re-proven at the service level).
3. Reliability gate survives: un-gated → no probability over the API AND no number in alerts;
   gated → the blessed number.
4. Idempotency: a composed cycle run twice → identical verdicts, zero duplicate notifications.
5. Advisory-only: no mutating/action endpoints anywhere in the composed API.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from ipo.calibration.calibrate import load_calibrator
from ipo.calibration.dataset import load_records_from_csv
from ipo.core.config import AppConfig, load_config
from ipo.core.interfaces import Calibrator
from ipo.core.types import IPORecord, ListingLabel, Verdict, VerdictType
from ipo.features.build import build_features
from ipo.model.scorer import WeightedScorer
from ipo.model.verdict import evaluate
from ipo.service.runner import Service, build_service
from ipo.service.transitions import TransitionStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CSV = _REPO_ROOT / "data" / "backfill" / "mainboard_ipos.csv"
_NIFTY = _REPO_ROOT / "data" / "backfill" / "nifty.csv"
_CAL = _REPO_ROOT / "models" / "calibrator.json"

pytestmark = pytest.mark.skipif(
    not (_CSV.is_file() and _NIFTY.is_file() and _CAL.is_file()),
    reason="backfill / calibrator artifacts not present",
)


class _ListRepo:
    """Minimal in-memory Repository over the backfill records (stands in for ingested data)."""

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


class _UngatedApply:
    """A calibrator that yields APPLY verdicts but has NOT passed the gate.

    This makes the reliability-gate check non-vacuous: there *is* an APPLY (so a number could
    leak), yet the gate is unpassed, so the engine must withhold it (probability ``None``) over
    both the API and the notifications.
    """

    version = "ungated-apply-test"

    def fit(self, raw_scores: list[float], labels: list[int]) -> None: ...

    def predict_proba(self, raw_score: float) -> float:
        return 0.95  # -> APPLY label, so there is a number that must be withheld

    @property
    def passes_reliability_gate(self) -> bool:
        return False


def _service(
    calibrator: Calibrator,
    *,
    refresh: Callable[[], None] | None = None,
) -> tuple[Service, list[IPORecord], AppConfig, list[str]]:
    config = load_config(
        env="dev", environ={}, overrides={"notify": {"enabled": True, "channel": "push"}}
    )
    records = load_records_from_csv(_CSV)
    pushed: list[str] = []
    # Isolated, empty transition log per service so this is a genuine cold start (first-cycle
    # crossings fire) — not primed by any persisted log under the real data dir.
    store = TransitionStore(Path(tempfile.mkdtemp()) / "verdict_transitions.json")
    service = build_service(
        config,
        repository=_ListRepo(records),
        calibrator=calibrator,
        nifty_path=_NIFTY,
        transition_store=store,
        push_transport=pushed.append,
        refresh=refresh,
    )
    return service, records, config, pushed


def _proba(verdicts: list[Verdict]) -> list[tuple[str, VerdictType, float | None]]:
    return [(v.ipo_id, v.verdict, v.probability) for v in verdicts]


def test_gate6_end_to_end_happy_path() -> None:
    refreshed = {"n": 0}

    def refresh() -> None:
        refreshed["n"] += 1

    service, records, config, pushed = _service(load_calibrator(_CAL), refresh=refresh)

    cycle, alerted = service.run_cycle()
    assert refreshed["n"] == 1  # INGEST ran (the scheduler's refresh hook)
    assert len(cycle.verdicts) == len(records)  # SCORE: every stored IPO scored
    assert len(alerted) > 0  # FIRE: APPLY crossings raised
    assert len(pushed) == len(alerted)  # one delivered notification per crossing

    client = TestClient(service.api)
    served = client.get("/ipos")  # SERVE over the API
    assert served.status_code == 200 and len(served.json()) == len(records)

    assert service.scheduler.next_cadence_minutes() in (
        config.scrape.cadence_minutes_default,
        config.scrape.cadence_minutes_subscription_window,
    )  # windowed cadence is live


def test_gate6_calibration_invariant_survives_composition() -> None:
    service, records, config, _ = _service(load_calibrator(_CAL))
    cycle, _ = service.run_cycle()

    flagged = sum(1 for v in cycle.verdicts if any("cold market" in w for w in v.watch))
    assert flagged > 0  # the regime flag fires THROUGH the running service

    scorer = WeightedScorer(config.feature_weights, config.features)
    calibrator = load_calibrator(_CAL)
    for rec in records:
        when = service.engine.decision_asof(rec)
        from_service = service.engine.verdict_for(rec)
        official_only = evaluate(
            rec,
            build_features(rec, when, config=config.features),  # regime ABSENT
            scorer=scorer,
            calibrator=calibrator,
            config=config,
        )
        assert from_service.probability == official_only.probability  # byte-identical


def test_gate6_reliability_gate_survives_composition() -> None:
    gated, records, _, _ = _service(load_calibrator(_CAL))
    rec = next(r for r in records if r.qib_sub is not None and r.listing_open is not None)
    gated_client = TestClient(gated.api)
    assert gated_client.get(f"/verdict/{rec.ipo_id}").json()["probability"] is not None

    ungated, _, _, ungated_pushed = _service(_UngatedApply())
    _, ungated_alerted = ungated.run_cycle()
    ungated_client = TestClient(ungated.api)

    # No probability over the API...
    assert ungated_client.get(f"/verdict/{rec.ipo_id}").json()["probability"] is None
    # ...and no number in the notifications either (gate not bypassed in either channel).
    assert len(ungated_alerted) > 0  # the placeholder does produce APPLY crossings (non-vacuous)
    assert all("n/a (uncalibrated)" in m for m in ungated_pushed)
    assert not any("%" in m for m in ungated_pushed)


def test_gate6_service_is_idempotent() -> None:
    service, _, _, pushed = _service(load_calibrator(_CAL))
    first, _ = service.run_cycle()
    pushed.clear()  # discard the first cycle's (legitimate) alerts
    second, second_alerted = service.run_cycle()

    assert _proba(second.verdicts) == _proba(first.verdicts)  # identical work
    assert second_alerted == []  # no duplicate APPLY crossings
    assert pushed == []  # no duplicate notifications delivered


def test_gate6_advisory_only_no_action_paths() -> None:
    service, _, _, _ = _service(load_calibrator(_CAL))
    mutating = {"POST", "PUT", "DELETE", "PATCH"}
    forbidden = ("order", "buy", "sell", "trade", "execute", "apply-now", "place")
    for route in service.api.routes:
        if isinstance(route, APIRoute):
            assert not ((route.methods or set()) & mutating)  # read-only verbs only
            assert not any(word in route.path.lower() for word in forbidden)  # no action paths
