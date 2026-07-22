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

import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from ipo.core.calendar import now_ist
from ipo.core.logging import get_logger
from ipo.core.types import IPORecord
from ipo.service.views import AllotmentRow, AllotmentView, IpoContextView, RegistrarInfo

_log = get_logger("ipo.service.ipo_context")

# How long after listing an IPO stays on the Allotment tab (allotment-status checking is only
# relevant for a short window after listing; keeps the tab bounded). F10: 5 days. `_stage` uses
# `days > _LISTED_VISIBLE_DAYS`, so a card listed EXACTLY N days ago is still shown and drops on day
# N+1 — i.e. visible through day 5, gone on day 6.
_LISTED_VISIBLE_DAYS = 5

# Beyond this age the cache is "stale": an absent field is treated as unproven ("we haven't looked")
# rather than "not published". One threshold for every field derived from the cache.
_CACHE_STALE_DAYS = 14


class IpoContext(BaseModel):
    """One IPO's cached Upstox context (display-only).

    Every field is nullable — absence degrades, never fabricates. Extend here (isin, …) as V3-11/10
    land; the store and the staleness rule do not change. ``lot_size`` (V3-8) is Upstox's bid-lot —
    NSE provides it on 0% of IPOs, so this is the *only* source — shown as an INDICATIVE planning
    figure (see IpoContextView), never as an exact reported value.
    """

    registrar: RegistrarInfo | None = None
    rhp_url: str | None = None
    lot_size: int | None = None
    isin: str | None = None
    industry: str | None = None


class _ContextCacheFile(BaseModel):
    """On-disk shape written by scripts/refresh_context.py (token-free), keyed by upper symbol."""

    refreshed_at: datetime | None = None
    ipos: dict[str, IpoContext] = {}


@dataclass(frozen=True)
class ContextSnapshot:
    """One consistent read of the cache — what a single request builds its whole view from.

    Taken once per request via :meth:`ContextStore.snapshot`. Without it, a view builder reading
    ``store.get()`` / ``store.available`` / ``store.refreshed_at`` per row re-checks the file on
    every access — so a refresh landing mid-request could blend rows from two cache versions into
    one response, with a freshness line matching neither. Building the whole view off one frozen
    snapshot closes that window, and drops the per-request cost from O(rows) stat calls to one.
    """

    available: bool
    refreshed_at: datetime | None
    by_symbol: Mapping[str, IpoContext]

    def get(self, ipo_id: str) -> IpoContext | None:
        """The cached context for an IPO (joined by symbol), or ``None`` if not in this snapshot."""
        return self.by_symbol.get(ipo_id.upper())


class ContextStore:
    """Read-only holder of the per-IPO Upstox context cache (v3 V3-5/V3-6; reload fixed in BUG-4).

    Loaded from a JSON file the external refresh job writes into the data dir. Missing/corrupt →
    ``available=False`` with an empty map (degrade honestly, never crash a surface). Keyed by NSE
    symbol upper-cased; an ``IPORecord`` joins by ``ipo_id.upper()``.

    **BUG-4 — the cache is re-read when the file changes.** This store used to load once at
    construction and never look again. ``runner.main`` builds it at boot, *before* the first refresh
    cycle writes the file — so a long-running process started against an empty data dir served
    ``not_loaded`` forever while correct data sat on disk (invisible on the desktop, which restarts
    constantly; fatal on a server that runs for weeks).

    The reload is **writer-agnostic by design, and must stay that way.** It reacts to the *file*
    changing, never to being told who wrote it. That is precisely why it covers the engine's own
    refresh cycle, an operator running ``scripts/refresh_context.py`` against the app's data dir,
    and a restore from the durable archive — with no coupling between this store and any of them.
    The tempting "just have the refresh cycle notify the store" alternative was **considered and
    rejected**: it encodes writer identity into the store, so the day a second writer appears it
    goes silently stale again — reintroducing the exact bug class this docstring exists to close.
    Do not "optimize" it back into a notify hook.

    **Cost.** Guarded by the file's ``(mtime_ns, size)``: steady state is one ``stat`` per read and
    **zero** parses. It re-parses only when the file actually moves, never on every read;
    ``test_unchanged_file_is_not_reparsed`` pins that by parse count, so this cannot quietly degrade
    into parse-on-every-read. Request handlers should take a :meth:`snapshot` rather than call
    :meth:`get` per row — that makes the whole request one reload check *and* one cache version.

    **A failed reload never erases good data.** ``__init__`` may legitimately start empty — at boot
    there genuinely is nothing. But a *reload* that hits a truncated or corrupt file keeps the
    last-good snapshot and logs, because turning one transient bad read into a blank Allotment tab
    trades a known-dead surface for an intermittently-dead one, which is worse.

    Thread-safe: the scheduler thread writes the file, the API thread reads it here. The snapshot is
    replaced wholesale under a lock and never mutated in place, so a reader either sees the old map
    or the new one — never a half-updated one.
    """

    def __init__(self, path: Path) -> None:
        """Open (or note the absence of) the cache at ``path`` and load it into memory."""
        self._path = path
        self._lock = threading.Lock()
        self._available = False
        self._refreshed_at: datetime | None = None
        self._by_symbol: dict[str, IpoContext] = {}
        # The change token: (mtime_ns, size), or None when the file does not exist. Starting at None
        # makes __init__ and every later read share ONE code path — an absent file at boot compares
        # equal and loads nothing; a present one compares unequal and loads.
        self._stamp: tuple[int, int] | None = None
        # Incremented on every parse ATTEMPT. Exists so the regression test can assert that an
        # unchanged file is not re-parsed — i.e. that the mtime guard is real and this has not
        # quietly degraded into parse-on-every-read.
        self._parse_count = 0
        with self._lock:
            self._reload_if_changed()

    def _current_stamp(self) -> tuple[int, int] | None:
        """The file's ``(mtime_ns, size)``, or ``None`` if it is absent/unstattable."""
        try:
            st = self._path.stat()
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def _reload_if_changed(self) -> None:
        """Re-read the cache iff the file moved since the last look. Caller must hold the lock.

        Size is checked alongside mtime because a same-second rewrite of a different length is a
        real change that a coarse mtime alone can miss.
        """
        stamp = self._current_stamp()
        if stamp == self._stamp:
            return
        # Record the new stamp even when the parse below fails, so a persistently corrupt file is
        # re-parsed once per change — not once per read.
        self._stamp = stamp
        if stamp is None:
            # The file vanished (mid-rotation, a wiped data dir). Absence is not evidence the data
            # is gone; keep the last-good snapshot rather than blanking the surface.
            _log.warning("ipo_context_cache_vanished", extra={"path": str(self._path)})
            return
        self._parse_count += 1
        try:
            cache = _ContextCacheFile.model_validate_json(self._path.read_text(encoding="utf-8"))
        except (ValueError, OSError, ValidationError) as exc:
            # At boot the snapshot is already empty, so this degrades honestly to "not loaded".
            # After boot it keeps whatever we last read successfully (see the class docstring).
            _log.warning(
                "ipo_context_cache_load_failed",
                extra={"error": str(exc), "kept_last_good": self._available},
            )
            return
        self._refreshed_at = cache.refreshed_at
        self._by_symbol = {k.upper(): v for k, v in cache.ipos.items()}
        self._available = True

    @property
    def available(self) -> bool:
        """True once a cache file has been loaded (fresh install → False, honest degradation)."""
        with self._lock:
            self._reload_if_changed()
            return self._available

    @property
    def refreshed_at(self) -> datetime | None:
        """When the cache was last written by the refresh job, or ``None`` if never/unavailable."""
        with self._lock:
            self._reload_if_changed()
            return self._refreshed_at

    def get(self, ipo_id: str) -> IpoContext | None:
        """The cached context for an IPO (joined by symbol), or ``None`` if not in the cache."""
        with self._lock:
            self._reload_if_changed()
            by_symbol = self._by_symbol  # replaced wholesale, never mutated → safe to read outside
        return by_symbol.get(ipo_id.upper())

    def snapshot(self) -> ContextSnapshot:
        """One consistent read of the cache: availability, freshness, and entries from one version.

        This is what a request handler should use. One reload check, one frozen view — so every row
        and the freshness line beside them describe the same file, and a refresh landing mid-request
        cannot blend two versions into one response.
        """
        with self._lock:
            self._reload_if_changed()
            return ContextSnapshot(self._available, self._refreshed_at, self._by_symbol)


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
    # ONE snapshot for the whole request: every row and the freshness line beside them describe the
    # same cache version, and a refresh landing mid-request cannot blend two versions into one
    # response. Also drops this handler from O(rows) reload checks to exactly one.
    snap = store.snapshot()
    rows: list[AllotmentRow] = []
    for record in records:
        stage = _stage(record, today)
        if stage is None:
            continue
        ctx = snap.get(record.ipo_id)
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
                    available=snap.available,
                    refreshed_at=snap.refreshed_at,
                    open_date=record.open_date,
                    today=today,
                ),
            )
        )
    rows.sort(key=lambda r: r.close_date, reverse=True)
    return AllotmentView(available=snap.available, refreshed_at=snap.refreshed_at, rows=rows)


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
    snap = store.snapshot()  # one snapshot per request — see build_allotment_view
    ctx = snap.get(record.ipo_id)
    reg = ctx.registrar if ctx else None
    rhp_url = ctx.rhp_url if ctx else None
    lot_size = ctx.lot_size if ctx else None
    isin = ctx.isin if ctx else None
    industry = ctx.industry if ctx else None

    def _state(present: bool) -> str:
        return field_state(
            present,
            available=snap.available,
            refreshed_at=snap.refreshed_at,
            open_date=record.open_date,
            today=today,
        )

    return IpoContextView(
        ipo_id=record.ipo_id,
        available=snap.available,
        refreshed_at=snap.refreshed_at,
        rhp_url=rhp_url,
        rhp_state=_state(rhp_url is not None),
        lot_size=lot_size,
        lot_state=_state(lot_size is not None),
        isin=isin,
        isin_state=_state(isin is not None),
        industry=industry,
        industry_state=_state(industry is not None),
        registrar=reg,
        registrar_state=_state(reg is not None),
    )
