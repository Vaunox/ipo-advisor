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
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path

import pytest

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


def _store(tmp_path: Path, refreshed_at: str, ipos: Mapping[str, object]) -> ContextStore:
    """Write a context cache ({SYMBOL: {registrar?, rhp_url?}}) and open a store over it."""
    path = tmp_path / "context" / "ipo_context.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"refreshed_at": refreshed_at, "ipos": ipos}), encoding="utf-8")
    return ContextStore(path)


def _store_reg(tmp_path: Path, registrars: Mapping[str, object]) -> ContextStore:
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
    reg = by_id["hasreg"].registrar
    assert reg is not None
    assert reg.website == "https://www.kfintech.com/"
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


def test_ipo_context_lot_size_present_and_stale(tmp_path: Path) -> None:
    rec = _rec("acme", close=date(2026, 7, 11))  # open_date 2026-06-01
    present = build_ipo_context(
        rec, _store(tmp_path, "2026-07-14T09:00:00+05:30", {"ACME": {"lot_size": 70}}), clock=_CLOCK
    )
    assert present.lot_size == 70 and present.lot_state == "present"
    # no lot in a current cache → not published yet
    cur = _store(tmp_path, "2026-07-14T09:00:00+05:30", {})
    none_cur = build_ipo_context(rec, cur, clock=_CLOCK)
    assert none_cur.lot_size is None and none_cur.lot_state == "unpublished"
    # cache predates the IPO → stale, NOT "not published" (same single rule as registrar + RHP)
    stale = build_ipo_context(rec, _store(tmp_path, "2026-05-01T09:00:00+05:30", {}), clock=_CLOCK)
    assert stale.lot_state == "stale"


def test_ipo_context_isin_and_industry_present_and_degrade(tmp_path: Path) -> None:
    """V3-11 reference fields flow through the same store + the one shared staleness rule."""
    rec = _rec("acme", close=date(2026, 7, 11))  # open_date 2026-06-01
    present = build_ipo_context(
        rec,
        _store(
            tmp_path,
            "2026-07-14T09:00:00+05:30",
            {"ACME": {"isin": "INE0ABC01019", "industry": "Cable"}},
        ),
        clock=_CLOCK,
    )
    assert present.isin == "INE0ABC01019" and present.isin_state == "present"
    assert present.industry == "Cable" and present.industry_state == "present"
    # current cache, no values → not-yet-published (honest, not a bare null)
    cur = _store(tmp_path, "2026-07-14T09:00:00+05:30", {})
    none_cur = build_ipo_context(rec, cur, clock=_CLOCK)
    assert none_cur.isin is None and none_cur.isin_state == "unpublished"
    assert none_cur.industry is None and none_cur.industry_state == "unpublished"
    # cache predates the IPO → stale (same single rule as registrar / RHP / lot_size)
    stale = build_ipo_context(rec, _store(tmp_path, "2026-05-01T09:00:00+05:30", {}), clock=_CLOCK)
    assert stale.isin_state == "stale" and stale.industry_state == "stale"


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


def test_scoring_path_cannot_transitively_reach_service_or_archive() -> None:
    """The model is *physically* unable to see display/context/archive data — via the real graph.

    A fresh interpreter imports EVERY module under features/ model/ calibration/ core/ (their whole
    transitive import closure) and asserts NO ``ipo.service.*`` OR ``ipo.archive.*`` module lands in
    ``sys.modules`` — the invariant behind V3-5/V3-6's boundary (the context store lives in
    ipo.service.*) and V3-2's (the durable archive lives in ipo.archive.*). Stronger + rename-proof:
    any indirect path from the scoring path into the service layer (context cache, /allotment join,
    RHP join) or the archive fails this test.

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
        "leaked = sorted(m for m in sys.modules if m.startswith(('ipo.service', 'ipo.archive')))\n"
        "print('LEAK ' + ','.join(leaked) if leaked else 'CLEAN')\n"
    )
    env = {**os.environ, "PYTHONPATH": str(src) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, env=env, timeout=120
    )
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    assert result.stdout.strip().splitlines()[-1] == "CLEAN", (
        "the scoring path transitively reaches ipo.service.* or ipo.archive.* — display/archive "
        f"data could reach the model: {result.stdout} {result.stderr}"
    )


# --- BUG-4: the cache is re-read when the file changes ------------------------------------------
#
# Before BUG-4, ContextStore loaded once at construction and never looked again. `runner.main`
# builds it at boot, BEFORE the first refresh cycle writes the file — so a long-running process
# started against an empty data dir served "not_loaded" forever while correct data sat on disk.
# Invisible on the desktop (constant restarts); fatal on a server that runs for weeks.


def test_bug4_store_started_empty_reflects_a_later_write(tmp_path: Path) -> None:
    """THE FAILURE CONDITION: empty data dir -> store built -> file written -> surface updates.

    This is the exact provisioning sequence of a fresh serving box, and the one the old store
    failed. No restart, no notification, no second construction — the same instance must simply
    start telling the truth once the data exists.
    """
    path = tmp_path / "context" / "ipo_context.json"
    store = ContextStore(path)  # boot: nothing on disk yet, honestly not loaded
    assert store.available is False
    assert store.get("knack") is None

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "refreshed_at": "2026-07-14T09:00:00+05:30",
                "ipos": {"KNACK": {"registrar": {"name": "MUFG Intime"}}},
            }
        ),
        encoding="utf-8",
    )

    assert store.available is True, "the surface stayed dead after the cache landed (BUG-4)"
    ctx = store.get("knack")
    assert ctx is not None and ctx.registrar is not None
    assert ctx.registrar.name == "MUFG Intime"
    assert store.refreshed_at is not None


def test_bug4_reload_picks_up_a_later_rewrite(tmp_path: Path) -> None:
    """Steady state, not just first write: a refreshed cache reaches the surface, no restart."""
    store = _store_reg(tmp_path, {"KNACK": {"name": "MUFG Intime"}})
    first = store.get("knack")
    assert first is not None and first.registrar is not None
    assert first.registrar.name == "MUFG Intime"

    path = tmp_path / "context" / "ipo_context.json"
    path.write_text(
        json.dumps(
            {
                "refreshed_at": "2026-07-15T09:00:00+05:30",
                "ipos": {"KNACK": {"registrar": {"name": "KFin Technologies"}}},
            }
        ),
        encoding="utf-8",
    )

    second = store.get("knack")
    assert second is not None and second.registrar is not None
    assert second.registrar.name == "KFin Technologies"


def test_bug4_failed_reload_keeps_the_last_good_snapshot(tmp_path: Path) -> None:
    """A torn/corrupt read must NOT blank a working surface.

    Degrading good data to empty on one bad read would trade a known-dead surface for an
    intermittently-dead one — strictly worse, and far harder to diagnose.
    """
    store = _store_reg(tmp_path, {"KNACK": {"name": "MUFG Intime"}})
    assert store.available is True

    path = tmp_path / "context" / "ipo_context.json"
    path.write_text('{"refreshed_at": "2026-07-15T09:00', encoding="utf-8")  # truncated mid-write

    assert store.available is True, "a corrupt reload erased good data"
    ctx = store.get("knack")
    assert ctx is not None and ctx.registrar is not None
    assert ctx.registrar.name == "MUFG Intime"


def test_bug4_vanished_file_keeps_the_last_good_snapshot(tmp_path: Path) -> None:
    """An absent file is not evidence the data is gone (mid-rotation, a wiped dir)."""
    store = _store_reg(tmp_path, {"KNACK": {"name": "MUFG Intime"}})
    assert store.available is True
    (tmp_path / "context" / "ipo_context.json").unlink()
    assert store.available is True
    assert store.get("knack") is not None


def test_bug4_corrupt_at_boot_still_degrades_honestly(tmp_path: Path) -> None:
    """Only __init__ may start empty — at boot there genuinely is no last-good to keep."""
    path = tmp_path / "ipo_context.json"
    path.write_text("{ not valid json", encoding="utf-8")
    store = ContextStore(path)
    assert store.available is False
    assert store.get("anything") is None


def test_unchanged_file_is_not_reparsed(tmp_path: Path) -> None:
    """THE GUARD AGAINST OPTION-B SILENTLY BECOMING OPTION-A.

    The mtime guard is the whole reason this fix is affordable: `build_allotment_view` calls `get()`
    once PER RECORD, so a parse-on-every-read would re-parse the entire cache once per row. If a
    future edit drops the guard, every read re-parses and this test fails — which is exactly when
    someone needs to be told.
    """
    store = _store_reg(tmp_path, {"KNACK": {"name": "MUFG Intime"}})
    assert store._parse_count == 1  # the construction-time load

    for _ in range(50):
        store.get("knack")
        _ = store.available
        _ = store.refreshed_at
    assert store._parse_count == 1, "unchanged file was re-parsed — the mtime guard is gone"

    # ...and a real change is still picked up (the guard must not be stuck shut either).
    (tmp_path / "context" / "ipo_context.json").write_text(
        json.dumps(
            {
                "refreshed_at": "2026-07-15T09:00:00+05:30",
                "ipos": {"KNACK": {"registrar": {"name": "KFin Technologies"}}},
            }
        ),
        encoding="utf-8",
    )
    assert store.get("knack") is not None
    assert store._parse_count == 2


def test_allotment_rows_all_come_from_one_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One request = one cache version. Rows must never blend two.

    `build_allotment_view` used to read `store.get()` + `store.available` + `refreshed_at`
    PER ROW — 3N+2 independent reload checks — so a refresh landing mid-request could produce a
    response whose rows came from different cache versions, with a freshness line matching none.

    The churn hook below rewrites the cache with a different registrar on EVERY reload check. Under
    the old per-row reads that yields a different name per row; under one snapshot every row agrees.
    """
    path = tmp_path / "context" / "ipo_context.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    def write(name: str) -> None:
        path.write_text(
            json.dumps(
                {
                    "refreshed_at": "2026-07-14T09:00:00+05:30",
                    "ipos": {s: {"registrar": {"name": name}} for s in ("AAA", "BBB", "CCC")},
                }
            ),
            encoding="utf-8",
        )

    write("REG-0")
    store = ContextStore(path)
    real_stamp = store._current_stamp
    churns = {"n": 0}

    def churning_stamp() -> tuple[int, int] | None:
        churns["n"] += 1
        write(f"REG-{churns['n']}")  # the file moves under us on every single check
        return real_stamp()

    monkeypatch.setattr(store, "_current_stamp", churning_stamp)

    closed = date(2026, 7, 3)
    view = build_allotment_view(
        [_rec("aaa", close=closed), _rec("bbb", close=closed), _rec("ccc", close=closed)],
        store,
        clock=lambda: datetime(2026, 7, 6, 10, 0),
    )

    assert len(view.rows) == 3
    names = {r.registrar.name for r in view.rows if r.registrar is not None}
    assert len(names) == 1, f"rows blended across cache versions: {sorted(map(str, names))}"
    assert churns["n"] == 1, f"expected ONE reload check for the whole request, got {churns['n']}"


def test_ipo_context_detail_uses_one_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same guarantee on the detail surface: 13 reads of the store, one view of the cache."""
    store = _store(
        tmp_path,
        "2026-07-14T09:00:00+05:30",
        {"KNACK": {"registrar": {"name": "MUFG Intime"}, "rhp_url": "https://x/y.pdf"}},
    )
    checks = {"n": 0}
    real_stamp = store._current_stamp

    def counting_stamp() -> tuple[int, int] | None:
        checks["n"] += 1
        return real_stamp()

    monkeypatch.setattr(store, "_current_stamp", counting_stamp)

    view = build_ipo_context(
        _rec("knack", close=date(2026, 7, 3)), store, clock=lambda: datetime(2026, 7, 6, 10, 0)
    )
    assert view.registrar is not None and view.rhp_url is not None
    assert checks["n"] == 1, f"expected ONE reload check for the whole request, got {checks['n']}"
