"""Allotment tab context (v3 V3-6) — the registrar cache the Allotment tab reads. DISPLAY ONLY.

This module is the whole registrar data path on the app side, and it is deliberately walled off from
the model:

* The registrar data lives in its OWN store (a JSON cache file), keyed by symbol, with its OWN type
  (``RegistrarInfo``) — it is **never** an ``IPORecord`` field. The feature builder
  (``features/build.py``) only ever sees ``IPORecord``, so a registrar value is **physically
  incapable** of reaching a feature vector. This is a structural guarantee (import-graph provable:
  nothing under ``features/model/calibration/core`` imports this module), not a careful promise.
* The app only READS this cache. It never fetches it — the fetch is an external, VM-runnable job
  (``scripts/refresh_allotment.py``) that writes the cache into the app's data plane (the data dir),
  exactly the fetch→data_dir→read shape the NSE feed already uses. So the feature is **severable**
  (Upstox down → the operator/VM can't refresh, but verdicts/live-signals are untouched) and, when
  the VM data layer (Part II) lands, this cache becomes VM-primary/local-fallback along with every
  other feed — one data pattern, a trivial swap, not a parallel path.
* It **degrades honestly**: a missing/unreadable cache reports ``available=False`` (the tab says
  so), and an IPO with no cache entry gets ``registrar=None`` ("not yet available") — never a blank
  card, never a stale registrar shown as current.

Upstox context data (Part IV) is display-only by rule; nothing here may ever become a scoring input.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from ipo.core.calendar import now_ist
from ipo.core.logging import get_logger
from ipo.core.types import IPORecord
from ipo.service.views import AllotmentRow, AllotmentView, RegistrarInfo

_log = get_logger("ipo.service.allotment_context")

# How long after listing an IPO stays on the Allotment tab. Allotment-status checking is only
# relevant for a short window after listing; past this the row drops off (keeps the tab bounded,
# same instinct as the alert-retention window).
_LISTED_VISIBLE_DAYS = 7

# Beyond this age a cache is "stale": an absent registrar is treated as unproven ("we haven't
# looked") rather than "not published". Registrar assignment is fixed at RHP filing, so a cache this
# old has likely missed newer IPOs — the honest read is "unknown", not "absent".
_CACHE_STALE_DAYS = 14


class _CacheFile(BaseModel):
    """On-disk shape written by scripts/refresh_allotment.py (token-free)."""

    refreshed_at: datetime | None = None
    registrars: dict[str, RegistrarInfo] = {}


class AllotmentStore:
    """Read-only holder of the registrar cache (v3 V3-6).

    Loaded from a JSON file the external refresh job writes into the data dir. Missing or corrupt →
    ``available=False`` with an empty map (degrade honestly, never crash the tab). Keys are the NSE
    symbol upper-cased; an ``IPORecord`` joins by ``ipo_id.upper()``.
    """

    def __init__(self, path: Path) -> None:
        """Open (or note the absence of) the cache at ``path`` and load it into memory."""
        self._path = path
        self._available = False
        self._refreshed_at: datetime | None = None
        self._by_symbol: dict[str, RegistrarInfo] = {}
        if path.is_file():
            try:
                cache = _CacheFile.model_validate_json(path.read_text(encoding="utf-8"))
                self._refreshed_at = cache.refreshed_at
                self._by_symbol = {k.upper(): v for k, v in cache.registrars.items()}
                self._available = True
            except (ValueError, OSError, ValidationError) as exc:
                _log.warning("allotment_cache_load_failed", extra={"error": str(exc)})

    @property
    def available(self) -> bool:
        """True once a cache file has been loaded (fresh install → False, honest degradation)."""
        return self._available

    @property
    def refreshed_at(self) -> datetime | None:
        """When the cache was last written by the refresh job, or ``None`` if never/unavailable."""
        return self._refreshed_at

    def get(self, ipo_id: str) -> RegistrarInfo | None:
        """The registrar block for an IPO (joined by symbol), or ``None`` if not in the cache."""
        return self._by_symbol.get(ipo_id.upper())


def _stage(record: IPORecord, today: date) -> str | None:
    """The allotment-lifecycle stage of ``record`` as of ``today``, or ``None`` if out of scope.

    In scope = the book has fully closed (allotment is only relevant after bidding ends) up to a
    short window after listing. Open/upcoming IPOs and long-listed IPOs are out of scope.
    """
    if record.close_date >= today:
        return None  # still open / upcoming — allotment not relevant yet
    listed = record.listing_date is not None and record.listing_date <= today
    if listed:
        assert record.listing_date is not None
        if (today - record.listing_date).days > _LISTED_VISIBLE_DAYS:
            return None  # listed a while ago — allotment check is moot, drop it
        return "listed"
    return "awaiting allotment"


def _registrar_state(
    reg: RegistrarInfo | None,
    *,
    available: bool,
    refreshed_at: datetime | None,
    open_date: date,
    today: date,
) -> str:
    """Why a registrar is (un)available — so an absence never lies about its cause (v3 V3-6).

    See ``AllotmentRow.registrar_state``: distinguishing "not yet published" from "cache is stale"
    is the honest-degradation rule taken one level deeper — the app reasons about freshness instead
    of leaving the user to compare a timestamp against the IPO's dates.
    """
    if reg is not None:
        return "present"
    if not available:
        return "not_loaded"
    if refreshed_at is None:
        return "stale"
    refreshed = refreshed_at.date()
    if refreshed < open_date or (today - refreshed).days > _CACHE_STALE_DAYS:
        return "stale"  # refreshed before this IPO existed, or too old to trust the absence
    return "unpublished"  # looked at/after it opened, recently, found nothing → not published yet


def build_allotment_view(
    records: Iterable[IPORecord],
    store: AllotmentStore,
    *,
    clock: Callable[[], datetime] = now_ist,
) -> AllotmentView:
    """Join IPOs at/past the allotment stage with the registrar cache (read-only, display-only).

    The registrar block is attached to the *view row* only — never back onto the ``IPORecord`` — so
    it stays outside the scoring path by construction. Sorted most-recently-closed first.
    """
    today = clock().date()
    rows: list[AllotmentRow] = []
    for record in records:
        stage = _stage(record, today)
        if stage is None:
            continue
        reg = store.get(record.ipo_id)
        rows.append(
            AllotmentRow(
                ipo_id=record.ipo_id,
                name=record.name,
                stage=stage,
                close_date=record.close_date,
                listing_date=record.listing_date,
                registrar=reg,
                registrar_state=_registrar_state(
                    reg,
                    available=store.available,
                    refreshed_at=store.refreshed_at,
                    open_date=record.open_date,
                    today=today,
                ),
            )
        )
    rows.sort(key=lambda r: r.close_date, reverse=True)
    return AllotmentView(available=store.available, refreshed_at=store.refreshed_at, rows=rows)
