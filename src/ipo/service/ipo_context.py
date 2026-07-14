"""Upstox per-IPO context cache (v3 V3-5/V3-6, generalized) — the ONE display-only Upstox store.

Every per-IPO Upstox *details* field the app surfaces — the registrar (V3-6), the RHP link (V3-5),
and later lot_size (V3-8), isin/industry/cut_off_price (V3-11), the anchor list (V3-10) — lives
here, in ONE cache, read through ONE store, with ONE staleness rule. Five features, one path — not
five parallel caches/scripts/staleness rules drifting apart (the failure class behind BUG 2's copies
and BUG 3's caches). Adding a field later is: capture it in refresh_context.py, add it to the entry,
read it through this store — no new plumbing.

It is walled off from the model exactly as before (structural, import-graph provable):

* Context data lives in its OWN store (a JSON cache) with its OWN types — never an ``IPORecord``
  field. ``features/build.py`` only sees ``IPORecord``, so no context value can reach a feature.
  Guarded by tests/unit/test_ipo_context.py: no ``ipo.service.*`` module is reachable from the
  transitive import closure of features/model/calibration/core.
* The app only READS this cache. The fetch is an external, VM-runnable job
  (scripts/refresh_context.py) writing into the data plane — the fetch→data_dir→read shape every
  feed uses. Severable (Upstox down never touches verdicts) and VM-primary/local-fallback when Part
  II lands.
* Honest degradation via ONE store-level rule (``field_state``): a value is present / not-yet-
  published (cache current, still absent) / stale (cache predates the IPO or is past threshold) /
  not-loaded (no cache). So a missing RHP or registrar never lies about WHY it's missing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from ipo.core.calendar import now_ist
from ipo.core.logging import get_logger
from ipo.core.types import IPORecord
from ipo.service.views import AllotmentRow, AllotmentView, IpoContextView, RegistrarInfo

_log = get_logger("ipo.service.ipo_context")

# How long after listing an IPO stays on the Allotment tab (allotment-status checking is only
# relevant for a short window after listing; keeps the tab bounded).
_LISTED_VISIBLE_DAYS = 7

# Beyond this age the cache is "stale": an absent field is treated as unproven ("we haven't looked")
# rather than "not published". One threshold for every field derived from the cache.
_CACHE_STALE_DAYS = 14


class IpoContext(BaseModel):
    """One IPO's cached Upstox context (display-only).

    Every field is nullable — absence degrades, never fabricates. Extend here (lot_size, isin, …) as
    V3-8/11/10 land; the store and the staleness rule do not change.
    """

    registrar: RegistrarInfo | None = None
    rhp_url: str | None = None


class _ContextCacheFile(BaseModel):
    """On-disk shape written by scripts/refresh_context.py (token-free), keyed by upper symbol."""

    refreshed_at: datetime | None = None
    ipos: dict[str, IpoContext] = {}


class ContextStore:
    """Read-only holder of the per-IPO Upstox context cache (v3 V3-5/V3-6).

    Loaded from a JSON file the external refresh job writes into the data dir. Missing/corrupt →
    ``available=False`` with an empty map (degrade honestly, never crash a surface). Keyed by NSE
    symbol upper-cased; an ``IPORecord`` joins by ``ipo_id.upper()``.
    """

    def __init__(self, path: Path) -> None:
        """Open (or note the absence of) the cache at ``path`` and load it into memory."""
        self._path = path
        self._available = False
        self._refreshed_at: datetime | None = None
        self._by_symbol: dict[str, IpoContext] = {}
        if path.is_file():
            try:
                cache = _ContextCacheFile.model_validate_json(path.read_text(encoding="utf-8"))
                self._refreshed_at = cache.refreshed_at
                self._by_symbol = {k.upper(): v for k, v in cache.ipos.items()}
                self._available = True
            except (ValueError, OSError, ValidationError) as exc:
                _log.warning("ipo_context_cache_load_failed", extra={"error": str(exc)})

    @property
    def available(self) -> bool:
        """True once a cache file has been loaded (fresh install → False, honest degradation)."""
        return self._available

    @property
    def refreshed_at(self) -> datetime | None:
        """When the cache was last written by the refresh job, or ``None`` if never/unavailable."""
        return self._refreshed_at

    def get(self, ipo_id: str) -> IpoContext | None:
        """The cached context for an IPO (joined by symbol), or ``None`` if not in the cache."""
        return self._by_symbol.get(ipo_id.upper())


def field_state(
    present: bool,
    *,
    available: bool,
    refreshed_at: datetime | None,
    open_date: date,
    today: date,
) -> str:
    """The one store-level staleness rule (v3 V3-5/V3-6) — why a cached field is (un)available.

    Every field derived from the cache (registrar, RHP, …) inherits this — never a second copy. See
    ``AllotmentRow.registrar_state`` for the states: distinguishing "not yet published" from "cache
    is stale" is what stops an absence from lying about its cause.
    """
    if present:
        return "present"
    if not available:
        return "not_loaded"
    if refreshed_at is None:
        return "stale"
    refreshed = refreshed_at.date()
    if refreshed < open_date or (today - refreshed).days > _CACHE_STALE_DAYS:
        return "stale"  # refreshed before this IPO existed, or too old to trust the absence
    return "unpublished"  # looked at/after it opened, recently, found nothing → not published yet


def _stage(record: IPORecord, today: date) -> str | None:
    """The allotment-lifecycle stage of ``record`` as of ``today``, or ``None`` if out of scope.

    In scope = the book has fully closed (allotment is only relevant after bidding ends) up to a
    short window after listing. Open/upcoming IPOs and long-listed IPOs are out of scope.
    """
    if record.close_date >= today:
        return None
    listed = record.listing_date is not None and record.listing_date <= today
    if listed:
        assert record.listing_date is not None
        if (today - record.listing_date).days > _LISTED_VISIBLE_DAYS:
            return None
        return "listed"
    return "awaiting allotment"


def build_allotment_view(
    records: Iterable[IPORecord],
    store: ContextStore,
    *,
    clock: Callable[[], datetime] = now_ist,
) -> AllotmentView:
    """Join IPOs at/past the allotment stage with the registrar from the context cache (V3-6).

    The registrar is attached to the *view row* only — never back onto the ``IPORecord`` — so it
    stays outside the scoring path by construction. Sorted most-recently-closed first.
    """
    today = clock().date()
    rows: list[AllotmentRow] = []
    for record in records:
        stage = _stage(record, today)
        if stage is None:
            continue
        ctx = store.get(record.ipo_id)
        reg = ctx.registrar if ctx else None
        rows.append(
            AllotmentRow(
                ipo_id=record.ipo_id,
                name=record.name,
                stage=stage,
                close_date=record.close_date,
                listing_date=record.listing_date,
                registrar=reg,
                registrar_state=field_state(
                    reg is not None,
                    available=store.available,
                    refreshed_at=store.refreshed_at,
                    open_date=record.open_date,
                    today=today,
                ),
            )
        )
    rows.sort(key=lambda r: r.close_date, reverse=True)
    return AllotmentView(available=store.available, refreshed_at=store.refreshed_at, rows=rows)


def build_ipo_context(
    record: IPORecord,
    store: ContextStore,
    *,
    clock: Callable[[], datetime] = now_ist,
) -> IpoContextView:
    """One IPO's display-only Upstox context for the detail page (v3 V3-5: the RHP link + state).

    Read-only join of the record with the context cache; the cached values are attached to the view
    only, never to the ``IPORecord``, so nothing here can reach the model. Each field carries its
    own freshness state from the single ``field_state`` rule, so a missing RHP distinguishes "not
    filed yet" from "our cache predates the filing".
    """
    today = clock().date()
    ctx = store.get(record.ipo_id)
    reg = ctx.registrar if ctx else None
    rhp_url = ctx.rhp_url if ctx else None

    def _state(present: bool) -> str:
        return field_state(
            present,
            available=store.available,
            refreshed_at=store.refreshed_at,
            open_date=record.open_date,
            today=today,
        )

    return IpoContextView(
        ipo_id=record.ipo_id,
        available=store.available,
        refreshed_at=store.refreshed_at,
        rhp_url=rhp_url,
        rhp_state=_state(rhp_url is not None),
        registrar=reg,
        registrar_state=_state(reg is not None),
    )
