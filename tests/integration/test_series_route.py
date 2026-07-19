"""`GET /subscription-series/{ipo_id}` — the engine-side series fetch (v3-DP DP-3a).

The engine re-serves the VM's DP-2 route to the chart DP-3b will draw. What this file exists to
pin is the FOUR honest states staying distinct — above all ``not_recorded`` vs ``unavailable``.

Those two look identical on a naive wire (both "no samples"), and collapsing them would make the UI
claim an absence it cannot vouch for: "this IPO was never recorded" is a fact about the world, while
"we could not reach the VM" is a fact about our reachability. A chart that shows the first when the
truth is the second is lying to the operator.

Reuses the committed fixture matrix in ``tests/fixtures/series/`` and the ``_FakeVm``-shaped double
from ``test_data_plane.py`` rather than inventing new data.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ipo.core.types import IPORecord, Segment
from ipo.service.api import create_app
from ipo.vm.client import VmUnavailable
from ipo.vm.models import SeriesEnvelope, SeriesSample

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "series"
FULL = "fixture-testco"
GAPPED = "fixture-gapco"


def _record(ipo_id: str) -> IPORecord:
    return IPORecord(
        ipo_id=ipo_id,
        name=ipo_id.upper(),
        segment=Segment("mainboard"),
        price_band_low=100.0,
        price_band_high=110.0,
        open_date=date(2026, 5, 15),
        close_date=date(2026, 5, 19),
        qib_sub=3.0,
        captured_at=datetime(2026, 5, 19, 17, 0),
    )


def _envelope_from_fixture(ipo_id: str) -> SeriesEnvelope:
    """Build the envelope the VM would return, from the committed store-shaped fixture.

    Mirrors DP-2's server projection: the stored rows carry `raw_response`/`categories`, the wire
    does not — so going through this conversion is what keeps the test honest about the shape the
    engine actually receives.
    """
    rows = json.loads((_FIXTURES / f"{ipo_id}.json").read_text(encoding="utf-8"))
    keep = (
        "schema_version",
        "captured_at",
        "source_update_time",
        "qib_sub",
        "nii_sub",
        "snii_sub",
        "bnii_sub",
        "retail_sub",
        "total_sub",
    )
    samples = [SeriesSample(**{k: r.get(k) for k in keep}) for r in rows]
    return SeriesEnvelope(
        refreshed_at=max(r["captured_at"] for r in rows), ipo_id=ipo_id, samples=samples
    )


class _FakeVm:
    """The VM client double — same shape as ``test_data_plane._FakeVm``, plus ``fetch_series``."""

    def __init__(self, *, series: SeriesEnvelope | None = None, fail: bool = False) -> None:
        self._series, self._fail = series, fail
        self.series_calls = 0
        self.records_calls = 0
        self.context_calls = 0

    def fetch_records(self) -> object:
        self.records_calls += 1
        raise AssertionError("the series route must never fetch records")

    def fetch_context(self) -> object:
        self.context_calls += 1
        raise AssertionError("the series route must never fetch context")

    def fetch_series(self, ipo_id: str) -> SeriesEnvelope:
        self.series_calls += 1
        if self._fail:
            raise VmUnavailable("vm down")
        assert self._series is not None
        return self._series


class _Repo:
    def __init__(self, records: list[IPORecord]) -> None:
        self._records = records

    def list_all(self) -> list[IPORecord]:
        return list(self._records)

    def get(self, ipo_id: str) -> IPORecord | None:
        return next((r for r in self._records if r.ipo_id == ipo_id), None)

    def upsert(self, record: IPORecord) -> None:
        raise NotImplementedError

    def upsert_many(self, records: list[IPORecord]) -> None:
        raise NotImplementedError


class _Engine:
    """Minimal engine stand-in — the route only calls ``get_record``."""

    def __init__(self, records: list[IPORecord]) -> None:
        self._repo = _Repo(records)

    def get_record(self, ipo_id: str) -> IPORecord | None:
        return self._repo.get(ipo_id)


def _client(vm: object | None, ipo_ids: tuple[str, ...] = (FULL, GAPPED)) -> TestClient:
    from typing import cast

    from ipo.service.engine import VerdictEngine
    from ipo.vm.client import VmClient

    engine = cast(VerdictEngine, _Engine([_record(i) for i in ipo_ids]))
    return TestClient(create_app(engine, vm_client=cast(VmClient, vm)))


# --- the four honest states -------------------------------------------------


def test_state1_vm_up_with_series_serves_samples(caplog: pytest.LogCaptureFixture) -> None:
    vm = _FakeVm(series=_envelope_from_fixture(FULL))
    with caplog.at_level(logging.INFO, logger="ipo.service.api"):
        body = _client(vm).get(f"/subscription-series/{FULL}").json()

    assert body["state"] == "recorded"
    assert body["available"] is True
    assert len(body["samples"]) == 48
    assert vm.series_calls == 1
    assert any(r.message == "series_from_vm" for r in caplog.records), "not logged for the console"


def test_state2_vm_up_no_series_is_not_recorded_NOT_unavailable() -> None:
    """The History-5 case: the VM answered, and the honest answer is 'nothing was ever banked'."""
    vm = _FakeVm(series=SeriesEnvelope(refreshed_at=None, ipo_id=FULL, samples=[]))
    body = _client(vm).get(f"/subscription-series/{FULL}").json()

    assert body["state"] == "not_recorded"
    assert body["available"] is True, "the VM answered — the answer itself is trustworthy"
    assert body["samples"] == []
    assert body["refreshed_at"] is None


def test_state3_vm_down_is_unavailable_NOT_empty(caplog: pytest.LogCaptureFixture) -> None:
    """We do not know what the series holds — saying 'empty' would assert an absence we can't back.

    There is deliberately no local fallback: the recorder is VM-only, so no local series exists.
    """
    vm = _FakeVm(fail=True)
    with caplog.at_level(logging.WARNING, logger="ipo.service.api"):
        body = _client(vm).get(f"/subscription-series/{FULL}").json()

    assert body["state"] == "unavailable"
    assert body["available"] is False
    assert body["samples"] == []
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(r.message == "vm_series_unavailable" for r in warnings), "silent VM failure"
    assert any(getattr(r, "ipo_id", None) == FULL for r in warnings), "warning must name the IPO"


def test_state4_dark_ship_no_vm_configured_is_not_loaded() -> None:
    """No VM at all — the app behaves as before the VM existed. Not an error, and not 'empty'."""
    body = _client(None).get(f"/subscription-series/{FULL}").json()

    assert body["state"] == "not_loaded"
    assert body["available"] is False
    assert body["samples"] == []


def test_the_four_states_are_mutually_distinguishable() -> None:
    """THE load-bearing assertion: a UI must be able to tell all four apart from the payload alone.

    Especially not_recorded vs unavailable — they differ in BOTH `available` and `state`, so a
    chart cannot accidentally render "never watched" when the truth is "couldn't reach the VM".
    """
    seen = {}
    seen["recorded"] = (
        _client(_FakeVm(series=_envelope_from_fixture(FULL)))
        .get(f"/subscription-series/{FULL}")
        .json()
    )
    seen["not_recorded"] = (
        _client(_FakeVm(series=SeriesEnvelope(refreshed_at=None, ipo_id=FULL, samples=[])))
        .get(f"/subscription-series/{FULL}")
        .json()
    )
    seen["unavailable"] = _client(_FakeVm(fail=True)).get(f"/subscription-series/{FULL}").json()
    seen["not_loaded"] = _client(None).get(f"/subscription-series/{FULL}").json()

    signatures = {k: (v["available"], v["state"]) for k, v in seen.items()}
    assert len(set(signatures.values())) == 4, f"states collapsed: {signatures}"
    assert signatures["not_recorded"] != signatures["unavailable"]


# --- freshness, pass-through shape, degradation -----------------------------


def test_per_ipo_freshness_passes_through_not_the_global_clock() -> None:
    env = _envelope_from_fixture(FULL)
    body = _client(_FakeVm(series=env)).get(f"/subscription-series/{FULL}").json()
    assert body["refreshed_at"] is not None
    assert datetime.fromisoformat(body["refreshed_at"]) == max(
        datetime.fromisoformat(s.captured_at.isoformat()) for s in env.samples
    )


def test_a_fetch_gap_survives_the_engine_hop() -> None:
    """DP-1 banks nothing on a failed fetch; the engine must not helpfully fill the hole either."""
    body = (
        _client(_FakeVm(series=_envelope_from_fixture(GAPPED)))
        .get(f"/subscription-series/{GAPPED}")
        .json()
    )
    times = [datetime.fromisoformat(s["captured_at"]) for s in body["samples"]]
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert max(gaps).total_seconds() > 30 * 60, "the gap was smoothed away"


def test_wire_projection_is_not_re_widened() -> None:
    """The engine re-serves DP-2's trimmed shape; it must not re-add the raw blob on this hop."""
    body = (
        _client(_FakeVm(series=_envelope_from_fixture(FULL)))
        .get(f"/subscription-series/{FULL}")
        .json()
    )
    sample = body["samples"][0]
    assert "raw_response" not in sample
    assert "categories" not in sample
    assert "captured_at" in sample and "qib_sub" in sample


def test_unknown_ipo_is_404_distinct_from_a_known_ipo_with_no_series() -> None:
    """A bad request vs an honest empty — the same distinction /context/{ipo_id} already makes."""
    vm = _FakeVm(series=SeriesEnvelope(refreshed_at=None, ipo_id=FULL, samples=[]))
    client = _client(vm)

    assert client.get("/subscription-series/no-such-ipo").status_code == 404
    known = client.get(f"/subscription-series/{FULL}")
    assert known.status_code == 200 and known.json()["state"] == "not_recorded"


# --- the route stays walled --------------------------------------------------


def test_the_series_route_never_triggers_records_or_context_fetches() -> None:
    """It is ON-DEMAND, not part of the 30-min cycle.

    Pins the approved side effect of hoisting the VM client: the API now holds the same client the
    cycle uses, so this proves the new wiring did not make a page-open start doing ingest work.
    ``_FakeVm`` raises on either, so a stray call fails loudly rather than passing quietly.
    """
    vm = _FakeVm(series=_envelope_from_fixture(FULL))
    _client(vm).get(f"/subscription-series/{FULL}")
    assert vm.series_calls == 1
    assert vm.records_calls == 0
    assert vm.context_calls == 0


def test_series_route_is_get_only() -> None:
    """Belt-and-suspenders beside the all-routes read-only test, which covers this automatically."""
    client = _client(_FakeVm(series=_envelope_from_fixture(FULL)))
    for verb in ("post", "put", "patch", "delete"):
        assert getattr(client, verb)(f"/subscription-series/{FULL}").status_code == 405


def test_route_registers_as_get_in_the_app() -> None:
    from typing import cast

    from ipo.service.engine import VerdictEngine

    app = create_app(cast(VerdictEngine, _Engine([_record(FULL)])), vm_client=None)
    route = next(r for r in app.routes if getattr(r, "path", "") == "/subscription-series/{ipo_id}")
    assert set(getattr(route, "methods", set())) == {"GET"}
