"""Allotment tab context (v3 V3-6) — the registrar cache reader + the display-only join.

Asserts: the store degrades honestly (missing/corrupt → available=False, never crash); the join
scopes to IPOs at/past the allotment stage (closed → awaiting; recently listed → listed; long-listed
and open/upcoming excluded); the registrar attaches only to the view row (never the record); and a
missing per-IPO entry degrades to ``registrar=None``. Offline + deterministic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
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


def _store_refreshed(tmp_path: Path, refreshed_at: str, registrars: dict) -> AllotmentStore:
    path = tmp_path / "registrar_info.json"
    path.write_text(
        json.dumps({"refreshed_at": refreshed_at, "registrars": registrars}), encoding="utf-8"
    )
    return AllotmentStore(path)


# --- registrar_state: distinguish "not yet published" from "cache is stale" (v3 V3-6) ----------


def test_state_present(tmp_path: Path) -> None:
    store = _store_with(tmp_path, {"HASREG": {"name": "KFin"}})
    view = build_allotment_view([_rec("hasreg", close=date(2026, 7, 11))], store, clock=_CLOCK)
    assert view.rows[0].registrar_state == "present"


def test_state_unpublished_when_cache_is_current(tmp_path: Path) -> None:
    # cache refreshed 2026-07-14 (≥ open 2026-06-01, and recent), no entry → genuinely not published
    store = _store_with(tmp_path, {})  # refreshed_at 2026-07-14T09:00
    view = build_allotment_view([_rec("noreg", close=date(2026, 7, 11))], store, clock=_CLOCK)
    assert view.rows[0].registrar_state == "unpublished"


def test_state_stale_when_cache_predates_the_ipo(tmp_path: Path) -> None:
    # refreshed 2026-05-01 — BEFORE this IPO opened (2026-06-01) → we never looked → stale
    store = _store_refreshed(tmp_path, "2026-05-01T09:00:00+05:30", {})
    view = build_allotment_view([_rec("noreg", close=date(2026, 7, 11))], store, clock=_CLOCK)
    assert view.rows[0].registrar_state == "stale"


def test_state_stale_when_cache_past_threshold(tmp_path: Path) -> None:
    # refreshed 2026-06-15 (≥ open) but 29 days before "today" (> 14-day threshold) → stale
    store = _store_refreshed(tmp_path, "2026-06-15T09:00:00+05:30", {})
    view = build_allotment_view([_rec("noreg", close=date(2026, 7, 11))], store, clock=_CLOCK)
    assert view.rows[0].registrar_state == "stale"


def test_state_not_loaded_when_no_cache(tmp_path: Path) -> None:
    store = AllotmentStore(tmp_path / "missing.json")
    view = build_allotment_view([_rec("x", close=date(2026, 7, 11))], store, clock=_CLOCK)
    assert view.rows[0].registrar_state == "not_loaded"


def test_view_available_false_when_no_cache(tmp_path: Path) -> None:
    store = AllotmentStore(tmp_path / "missing.json")  # never loaded
    view = build_allotment_view([_rec("x", close=date(2026, 7, 11))], store, clock=_CLOCK)
    assert view.available is False  # tab shows "not loaded"…
    assert len(view.rows) == 1  # …but the in-scope IPO still lists (registrar None)
    assert view.rows[0].registrar is None


# --- structural boundary (v3 V3-6) — a permanent regression guard ------------------------------


_SCORING_PKGS = ("features", "model", "calibration", "core")


def test_scoring_path_has_no_direct_registrar_reference() -> None:
    """Fast, readable direct check: no scoring-path FILE names the V3-6 allotment/registrar symbols.

    Complements the transitive check below — this catches an obvious direct import at a glance; the
    transitive one catches the sneakier case (a shared util imported by the scoring path that itself
    imports the allotment context).
    """
    root = Path(__file__).resolve().parents[2] / "src" / "ipo"
    forbidden = (
        "allotment_context",
        "AllotmentStore",
        "AllotmentView",
        "AllotmentRow",
        "RegistrarInfo",
        "build_allotment_view",
    )
    offenders = [
        f"{py.relative_to(root)} references {sym}"
        for pkg in _SCORING_PKGS
        for py in (root / pkg).rglob("*.py")
        for sym in forbidden
        if sym in py.read_text(encoding="utf-8")
    ]
    assert not offenders, "registrar data must not reach the scoring path: " + "; ".join(offenders)


def test_scoring_path_cannot_transitively_reach_registrar_data() -> None:
    """The model must be *physically* unable to see registrar data — via the real import graph.

    A fresh interpreter imports EVERY module under features/ model/ calibration/ core/ (their whole
    transitive import closure) and asserts ``ipo.service.allotment_context`` never lands in
    ``sys.modules``. So even an indirect path — a scoring module importing an out-of-scope util that
    imports the allotment context — fails this test. Same class of structural guarantee as the
    GET-only API surface: if it ever breaks, a registrar value could reach a feature vector.

    Run in a subprocess because the pytest process itself has already imported the allotment context
    (via the API tests), so this process's ``sys.modules`` cannot answer the question.
    """
    src = Path(__file__).resolve().parents[2] / "src"
    probe = (
        "import importlib, pkgutil, sys\n"
        "import ipo.features, ipo.model, ipo.calibration, ipo.core\n"
        "for pkg in (ipo.features, ipo.model, ipo.calibration, ipo.core):\n"
        "    for m in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + '.'):\n"
        "        try:\n"
        "            importlib.import_module(m.name)\n"
        "        except Exception:\n"
        "            pass\n"
        "print('LEAK' if 'ipo.service.allotment_context' in sys.modules else 'CLEAN')\n"
    )
    env = {**os.environ, "PYTHONPATH": str(src) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, env=env, timeout=120
    )
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    assert result.stdout.strip().splitlines()[-1] == "CLEAN", (
        "the scoring path transitively imports ipo.service.allotment_context — registrar data can "
        f"reach the model: {result.stdout} {result.stderr}"
    )
