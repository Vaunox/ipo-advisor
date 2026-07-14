"""Per-IPO Upstox context cache (v3 V3-5/V3-6) — the store, the allotment join, the detail context.

Asserts: the store degrades honestly (missing/corrupt → available=False, never crash); the allotment
join scopes correctly and attaches the registrar to the view row only; ``build_ipo_context`` shows
the RHP link with the SAME single staleness rule (present / unpublished / stale / not_loaded); and
the structural boundary holds — no ``ipo.service.*`` module is reachable from the scoring path's
transitive import closure. Offline + deterministic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from ipo.core.types import IPORecord, Segment
from ipo.service.ipo_context import ContextStore, build_allotment_view, build_ipo_context

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


def _store(tmp_path: Path, refreshed_at: str, ipos: dict) -> ContextStore:
    """Write a context cache ({SYMBOL: {registrar?, rhp_url?}}) and open a store over it."""
    path = tmp_path / "context" / "ipo_context.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"refreshed_at": refreshed_at, "ipos": ipos}), encoding="utf-8")
    return ContextStore(path)


def _store_reg(tmp_path: Path, registrars: dict) -> ContextStore:
    """Convenience: a current cache carrying only registrars ({SYMBOL: registrar_fields})."""
    ipos = {k: {"registrar": v} for k, v in registrars.items()}
    return _store(tmp_path, "2026-07-14T09:00:00+05:30", ipos)


# --- store degradation -------------------------------------------------------------------------


def test_store_missing_file_is_unavailable(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "nope.json")
    assert store.available is False
    assert store.refreshed_at is None
    assert store.get("anything") is None


def test_store_corrupt_file_degrades(tmp_path: Path) -> None:
    path = tmp_path / "ipo_context.json"
    path.write_text("{ not valid json", encoding="utf-8")
    assert ContextStore(path).available is False  # never crashes a surface


def test_store_reads_and_keys_case_insensitively(tmp_path: Path) -> None:
    store = _store_reg(tmp_path, {"KNACK": {"name": "MUFG Intime", "short": "MUFG"}})
    assert store.available is True
    ctx = store.get("knack")  # joins by ipo_id regardless of case
    assert ctx is not None and ctx.registrar is not None
    assert ctx.registrar.name == "MUFG Intime"
    assert store.get("absent") is None


# --- allotment join (V3-6) ---------------------------------------------------------------------


def test_scope_excludes_open_and_upcoming(tmp_path: Path) -> None:
    store = _store_reg(tmp_path, {})
    records = [
        _rec("openbook", close=date(2026, 7, 20)),  # book still open
        _rec("upcoming", close=date(2026, 8, 1)),  # upcoming
    ]
    assert build_allotment_view(records, store, clock=_CLOCK).rows == []


def test_scope_awaiting_and_recently_listed_included(tmp_path: Path) -> None:
    store = _store_reg(tmp_path, {})
    records = [
        _rec("awaiting", close=date(2026, 7, 11)),
        _rec("justlisted", close=date(2026, 7, 8), listing=date(2026, 7, 12)),
    ]
    view = build_allotment_view(records, store, clock=_CLOCK)
    assert {r.ipo_id: r.stage for r in view.rows} == {
        "awaiting": "awaiting allotment",
        "justlisted": "listed",
    }


def test_scope_drops_long_listed(tmp_path: Path) -> None:
    store = _store_reg(tmp_path, {})
    records = [_rec("old", close=date(2026, 6, 28), listing=date(2026, 7, 4))]  # listed 10d ago
    assert build_allotment_view(records, store, clock=_CLOCK).rows == []


def test_join_attaches_registrar_or_none(tmp_path: Path) -> None:
    store = _store_reg(
        tmp_path, {"HASREG": {"name": "KFin Technologies", "website": "https://www.kfintech.com/"}}
    )
    records = [_rec("hasreg", close=date(2026, 7, 11)), _rec("noreg", close=date(2026, 7, 11))]
    by_id = {r.ipo_id: r for r in build_allotment_view(records, store, clock=_CLOCK).rows}
    assert by_id["hasreg"].registrar is not None
    assert by_id["hasreg"].registrar.website == "https://www.kfintech.com/"  # type: ignore[union-attr]
    assert by_id["noreg"].registrar is None


# --- one staleness rule, shared by registrar + RHP (v3 V3-5/V3-6) ------------------------------


def test_state_present(tmp_path: Path) -> None:
    store = _store_reg(tmp_path, {"HASREG": {"name": "KFin"}})
    view = build_allotment_view([_rec("hasreg", close=date(2026, 7, 11))], store, clock=_CLOCK)
    assert view.rows[0].registrar_state == "present"


def test_state_unpublished_when_cache_is_current(tmp_path: Path) -> None:
    store = _store_reg(tmp_path, {})  # refreshed 2026-07-14 (≥ open, recent), no entry
    view = build_allotment_view([_rec("noreg", close=date(2026, 7, 11))], store, clock=_CLOCK)
    assert view.rows[0].registrar_state == "unpublished"


def test_state_stale_when_cache_predates_the_ipo(tmp_path: Path) -> None:
    store = _store(tmp_path, "2026-05-01T09:00:00+05:30", {})  # before open 2026-06-01
    view = build_allotment_view([_rec("noreg", close=date(2026, 7, 11))], store, clock=_CLOCK)
    assert view.rows[0].registrar_state == "stale"


def test_state_stale_when_cache_past_threshold(tmp_path: Path) -> None:
    store = _store(tmp_path, "2026-06-15T09:00:00+05:30", {})  # 29d before "today" (> 14d)
    view = build_allotment_view([_rec("noreg", close=date(2026, 7, 11))], store, clock=_CLOCK)
    assert view.rows[0].registrar_state == "stale"


def test_state_not_loaded_when_no_cache(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "missing.json")
    view = build_allotment_view([_rec("x", close=date(2026, 7, 11))], store, clock=_CLOCK)
    assert view.rows[0].registrar_state == "not_loaded"
    assert view.available is False and len(view.rows) == 1 and view.rows[0].registrar is None


# --- detail context: the RHP link inherits the SAME staleness rule (v3 V3-5) -------------------


def test_ipo_context_rhp_present(tmp_path: Path) -> None:
    store = _store(
        tmp_path,
        "2026-07-14T09:00:00+05:30",
        {"ACME": {"rhp_url": "https://www.sebi.gov.in/filings/acme-rhp"}},
    )
    ctx = build_ipo_context(_rec("acme", close=date(2026, 7, 11)), store, clock=_CLOCK)
    assert ctx.rhp_url == "https://www.sebi.gov.in/filings/acme-rhp"
    assert ctx.rhp_state == "present"


def test_ipo_context_rhp_unpublished_vs_stale(tmp_path: Path) -> None:
    rec = _rec("acme", close=date(2026, 7, 11))  # open_date 2026-06-01
    # cache current, no rhp → not filed yet
    cur_store = _store(tmp_path, "2026-07-14T09:00:00+05:30", {})
    current = build_ipo_context(rec, cur_store, clock=_CLOCK)
    assert current.rhp_url is None and current.rhp_state == "unpublished"
    # cache predates the IPO → we never looked → stale, NOT "not filed"
    stale_store = _store(tmp_path, "2026-05-01T09:00:00+05:30", {})
    assert build_ipo_context(rec, stale_store, clock=_CLOCK).rhp_state == "stale"


def test_ipo_context_not_loaded(tmp_path: Path) -> None:
    ctx = build_ipo_context(
        _rec("acme", close=date(2026, 7, 11)), ContextStore(tmp_path / "missing.json"), clock=_CLOCK
    )
    assert ctx.available is False
    assert ctx.rhp_state == "not_loaded" and ctx.registrar_state == "not_loaded"


def test_ipo_context_carries_registrar_too(tmp_path: Path) -> None:
    store = _store(
        tmp_path,
        "2026-07-14T09:00:00+05:30",
        {"ACME": {"registrar": {"name": "Bigshare"}, "rhp_url": "https://x.sebi.gov.in/r"}},
    )
    ctx = build_ipo_context(_rec("acme", close=date(2026, 7, 11)), store, clock=_CLOCK)
    assert ctx.registrar is not None and ctx.registrar.name == "Bigshare"
    assert ctx.registrar_state == "present" and ctx.rhp_state == "present"


# --- structural boundary (v3 V3-5/V3-6) — a permanent regression guard -------------------------


_SCORING_PKGS = ("features", "model", "calibration", "core")


def test_scoring_path_has_no_direct_context_reference() -> None:
    """Fast, readable direct check: no scoring-path FILE names the context/registrar symbols.

    Complements the transitive check below (which catches the sneakier indirect case).
    """
    root = Path(__file__).resolve().parents[2] / "src" / "ipo"
    forbidden = (
        "ipo_context",
        "ContextStore",
        "IpoContextView",
        "AllotmentView",
        "AllotmentRow",
        "RegistrarInfo",
        "build_allotment_view",
        "build_ipo_context",
    )
    offenders = [
        f"{py.relative_to(root)} references {sym}"
        for pkg in _SCORING_PKGS
        for py in (root / pkg).rglob("*.py")
        for sym in forbidden
        if sym in py.read_text(encoding="utf-8")
    ]
    assert not offenders, "context data must not reach the scoring path: " + "; ".join(offenders)


def test_scoring_path_cannot_transitively_reach_the_service_layer() -> None:
    """The model must be *physically* unable to see any display/context data — via the real graph.

    A fresh interpreter imports EVERY module under features/ model/ calibration/ core/ (their whole
    transitive import closure) and asserts NO ``ipo.service.*`` module lands in ``sys.modules`` —
    the general invariant behind V3-5/V3-6's boundary (the context store lives in ipo.service.*),
    and it is stronger + rename-proof: any indirect path from the scoring path into the service
    layer — where the context cache, the /allotment join, or the RHP join live — fails this test.

    Run in a subprocess because the pytest process has already imported the service layer (via the
    API tests), so this process's ``sys.modules`` cannot answer the question.
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
        "leaked = sorted(m for m in sys.modules if m.startswith('ipo.service'))\n"
        "print('LEAK ' + ','.join(leaked) if leaked else 'CLEAN')\n"
    )
    env = {**os.environ, "PYTHONPATH": str(src) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, env=env, timeout=120
    )
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    assert result.stdout.strip().splitlines()[-1] == "CLEAN", (
        "the scoring path transitively reaches ipo.service.* — context data could reach the "
        f"model: {result.stdout} {result.stderr}"
    )
