"""Allotment tab context (v3 V3-6) — the registrar cache reader + the display-only join.

Asserts: the store degrades honestly (missing/corrupt → available=False, never crash); the join
scopes to IPOs at/past the allotment stage (closed → awaiting; recently listed → listed; long-listed
and open/upcoming excluded); the registrar attaches only to the view row (never the record); and a
missing per-IPO entry degrades to ``registrar=None``. Offline + deterministic.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from ipo.core.types import IPORecord, Segment
from ipo.service.allotment_context import AllotmentStore, build_allotment_view

_CLOCK = lambda: datetime(2026, 7, 14, 12, 0)  # noqa: E731 — fixed "today" = 2026-07-14


def _rec(ipo_id: str, *, close: date, listing: date | None = None) -> IPORecord:
    return IPORecord(
        ipo_id=ipo_id,
        name=ipo_id.upper() + " Ltd",
        segment=Segment("mainboard"),
        price_band_low=100.0,
        price_band_high=110.0,
        open_date=date(2026, 6, 1),
        close_date=close,
        listing_date=listing,
        qib_sub=5.0,
        captured_at=datetime(2026, 7, 1, 17, 0),
    )


def _store_with(tmp_path: Path, registrars: dict) -> AllotmentStore:
    path = tmp_path / "allotment" / "registrar_info.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"refreshed_at": "2026-07-14T09:00:00+05:30", "registrars": registrars}),
        encoding="utf-8",
    )
    return AllotmentStore(path)


# --- store degradation -------------------------------------------------------------------------


def test_store_missing_file_is_unavailable(tmp_path: Path) -> None:
    store = AllotmentStore(tmp_path / "nope.json")
    assert store.available is False
    assert store.refreshed_at is None
    assert store.get("anything") is None


def test_store_corrupt_file_degrades(tmp_path: Path) -> None:
    path = tmp_path / "registrar_info.json"
    path.write_text("{ not valid json", encoding="utf-8")
    store = AllotmentStore(path)
    assert store.available is False  # never crashes the tab


def test_store_reads_and_keys_case_insensitively(tmp_path: Path) -> None:
    store = _store_with(tmp_path, {"KNACK": {"name": "MUFG Intime", "short": "MUFG"}})
    assert store.available is True
    assert store.get("knack") is not None  # joins by ipo_id regardless of case
    assert store.get("KNACK").name == "MUFG Intime"  # type: ignore[union-attr]
    assert store.get("absent") is None


# --- scope + join ------------------------------------------------------------------------------


def test_scope_excludes_open_and_upcoming(tmp_path: Path) -> None:
    store = _store_with(tmp_path, {})
    records = [
        _rec("openbook", close=date(2026, 7, 20)),  # book still open (close in future)
        _rec("upcoming", close=date(2026, 8, 1)),  # upcoming
    ]
    view = build_allotment_view(records, store, clock=_CLOCK)
    assert view.rows == []  # neither is at the allotment stage yet


def test_scope_awaiting_and_recently_listed_included(tmp_path: Path) -> None:
    store = _store_with(tmp_path, {})
    records = [
        _rec("awaiting", close=date(2026, 7, 11)),  # closed 3 days ago, not listed
        _rec("justlisted", close=date(2026, 7, 8), listing=date(2026, 7, 12)),  # listed 2 days ago
    ]
    view = build_allotment_view(records, store, clock=_CLOCK)
    stages = {r.ipo_id: r.stage for r in view.rows}
    assert stages == {"awaiting": "awaiting allotment", "justlisted": "listed"}


def test_scope_drops_long_listed(tmp_path: Path) -> None:
    store = _store_with(tmp_path, {})
    # listed 10 days ago (> the 7-day visibility window) → allotment check moot, dropped
    records = [_rec("old", close=date(2026, 6, 28), listing=date(2026, 7, 4))]
    assert build_allotment_view(records, store, clock=_CLOCK).rows == []


def test_join_attaches_registrar_or_none(tmp_path: Path) -> None:
    store = _store_with(
        tmp_path,
        {"HASREG": {"name": "KFin Technologies", "website": "https://www.kfintech.com/"}},
    )
    records = [
        _rec("hasreg", close=date(2026, 7, 11)),
        _rec("noreg", close=date(2026, 7, 11)),  # no cache entry → registrar None
    ]
    view = build_allotment_view(records, store, clock=_CLOCK)
    by_id = {r.ipo_id: r for r in view.rows}
    assert by_id["hasreg"].registrar is not None
    assert by_id["hasreg"].registrar.website == "https://www.kfintech.com/"  # type: ignore[union-attr]
    assert by_id["noreg"].registrar is None  # honest "not yet available"
    assert view.available is True


def test_view_available_false_when_no_cache(tmp_path: Path) -> None:
    store = AllotmentStore(tmp_path / "missing.json")  # never loaded
    view = build_allotment_view([_rec("x", close=date(2026, 7, 11))], store, clock=_CLOCK)
    assert view.available is False  # tab shows "not loaded"…
    assert len(view.rows) == 1  # …but the in-scope IPO still lists (registrar None)
    assert view.rows[0].registrar is None


# --- structural boundary (v3 V3-6) — a permanent regression guard ------------------------------


def test_scoring_path_cannot_reach_registrar_data() -> None:
    """The model must be *physically* unable to see registrar data — proven, not promised.

    No file under features/ model/ calibration/ core/ may reference the V3-6 allotment context or
    its registrar types. This is the same class of guarantee as the GET-only API surface; if it ever
    breaks, a registrar field could leak into a feature vector and this test fails loudly.
    """
    root = Path(__file__).resolve().parents[2] / "src" / "ipo"
    scoring_path = ("features", "model", "calibration", "core")
    forbidden = (
        "allotment_context",
        "AllotmentStore",
        "AllotmentView",
        "AllotmentRow",
        "RegistrarInfo",
        "build_allotment_view",
    )
    offenders: list[str] = []
    for pkg in scoring_path:
        for py in (root / pkg).rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            for sym in forbidden:
                if sym in text:
                    offenders.append(f"{py.relative_to(root)} references {sym}")
    assert not offenders, "registrar data must not reach the scoring path: " + "; ".join(offenders)
