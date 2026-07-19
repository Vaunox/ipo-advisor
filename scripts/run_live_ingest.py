"""Run ONE live NSE ingest into a data dir (v3 V3-1) — the VM's records timer.

The VM data plane serves what the app would have scraped LOCALLY, so it must run the SAME live fetch
the app runs — NOT the seed pipeline (``run_ingest.py``, curated backfill), which would serve stale
historical data under a fresh ``refreshed_at`` (a BUG-1-class silent failure). This is a thin,
versioned entry point around the exact path ``service.runner._live_refresh`` uses: the same polite
``NseClient`` built from config, and the same ``refresh_from_nse`` — which writes BOTH
``ipo_records.parquet`` and the freshness ``ingest_state.json`` (the ``last_success`` /
``last_attempt_ok`` clock ``run_vm_server`` serves as ``refreshed_at`` and ``/status`` reports).
No parallel or simplified fetch path that could drift from the app's behaviour.

Deploy on the VM behind a systemd timer; ``run_vm_server.py`` then serves the result (read-only).

New-IPO onset trigger (v3, context-off-scoring-path): the 3x/day ``refresh_context.py`` baseline
leaves a genuinely new IPO's context fields empty for up to ~5-6h if it opens mid-interval. Since
this ingest cycle already knows exactly which ``ipo_id``s are new this run (diffed against what was
already in the store BEFORE the upsert), it fires one immediate single-symbol context pull per new
IPO — no separate "seen" set: the records store itself IS the durable seen-state, so a VM restart
never re-fires for an already-known open IPO. Dark-ships without ``UPSTOX_TOKEN``; a context-pull
failure is logged and never affects the records ingest (which has already completed by then).

    python scripts/run_live_ingest.py --data-dir <vm-data> [--env dev|prod]
"""

from __future__ import annotations

import argparse
import importlib.util
import os
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

from ipo.core.calendar import now_ist
from ipo.core.config import AppConfig, load_config
from ipo.core.logging import configure_logging, get_logger
from ipo.data.ingest.live import refresh_from_nse
from ipo.data.ingest.state import IngestStateStore
from ipo.data.sources.base import PoliteClient, RawCache
from ipo.data.sources.nse import NseClient
from ipo.data.store.repository import ParquetRepository
from ipo.series.models import SubscriptionSample
from ipo.series.recorder import SeriesSink
from ipo.series.state import RecorderStateStore
from ipo.series.store import SeriesWriteError, SubscriptionSeriesStore

_log = get_logger("ipo.scripts.run_live_ingest")


def _load_refresh_context() -> ModuleType:
    """Load scripts/refresh_context.py by path (it is deliberately not an importable package)."""
    path = Path(__file__).resolve().parent / "refresh_context.py"
    spec = importlib.util.spec_from_file_location("refresh_context", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_nse(config: AppConfig, data_dir: Path) -> NseClient:
    """Build the polite NSE client EXACTLY as ``service.runner._live_refresh`` does (no drift)."""
    client = PoliteClient(
        user_agent=config.scrape.user_agent,
        rate_limit_per_sec=config.scrape.rate_limit_per_sec,
        backoff_factor=config.scrape.backoff_factor,
        max_retries=config.scrape.max_retries,
        respect_robots=False,
    )
    return NseClient(client, RawCache(root=data_dir / "raw_cache"))


def live_ingest(nse: NseClient, data_dir: Path) -> int:
    """Run the app's exact live records scrape into ``data_dir``; return the record count.

    Calls the SAME ``refresh_from_nse(repo, nse, state=...)`` the app's local-scrape path uses, so
    it writes ``ipo_records.parquet`` AND ``ingest_state.json`` (the ``last_success`` the read-API
    serves as ``refreshed_at``). ``nse`` is injected so tests drive a canned source over it.
    """
    return live_ingest_new_ids(nse, data_dir)[0]


def live_ingest_new_ids(nse: NseClient, data_dir: Path) -> tuple[int, set[str]]:
    """Same path as ``live_ingest``, plus which ``ipo_id``s are new to the store this cycle.

    "New" is derived from the records store itself — a snapshot of ``ipo_id``s taken BEFORE the
    upsert, diffed against what's there after. No separate seen-set file: the parquet IS the durable
    seen-state, so a fresh process (or a VM restart) never re-derives "new" for an IPO the store
    already has, however it got there.
    """
    repo = ParquetRepository(data_dir)
    existing_ids = {r.ipo_id for r in repo.list_all()}
    state = IngestStateStore(data_dir / "ingest_state.json")
    # v3-DP DP-1. The sink is created HERE, in the VM's entry point, and NOT inside
    # `refresh_from_nse` — which is also the desktop's local-fallback leaf, so hooking it there
    # would start a recorder on every shipped `.exe` whenever the VM is unreachable.
    sink = SeriesSink()
    count = refresh_from_nse(repo, nse, state=state, sink=sink)
    new_ids = {r.ipo_id for r in repo.list_all()} - existing_ids
    # AFTER the current-state upsert has committed, never before.
    flush_series(data_dir, sink)
    return count, new_ids


def flush_series(data_dir: Path, sink: SeriesSink) -> int:
    """Bank this cycle's readings and record recorder health. NEVER raises — returns 0 on failure.

    Deliberately swallowing here is the whole point: current state and the verdicts derived from it
    have already been written by the time this runs, and a recorder problem must degrade to a gap
    in the series, never to a missed score. The failure is not silent — it is logged as a
    structured event AND persisted to the recorder state the Telegram digest's ``Recorder`` row
    reads, so it surfaces within one alert-check cycle.
    """
    now = now_ist()
    store = SubscriptionSeriesStore(data_dir)
    state_store = RecorderStateStore(data_dir)
    written = 0
    error: str | None = None

    by_ipo: dict[str, list[SubscriptionSample]] = {}
    for sample in sink.samples:
        by_ipo.setdefault(sample.ipo_id, []).append(sample)

    for ipo_id, samples in sorted(by_ipo.items()):
        try:
            written += store.append_many(ipo_id, samples)
        except (SeriesWriteError, OSError) as exc:
            error = f"{ipo_id}: {exc}"
            _log.error("series_write_failed", extra={"ipo_id": ipo_id, "error": str(exc)})

    try:
        state_store.record_cycle(now=now, in_window=sink.in_window, written=written, error=error)
    except OSError as exc:  # the health surface itself failing must still not break ingest
        _log.error("recorder_state_write_failed", extra={"error": str(exc)})

    _log.info(
        "series_recorder_cycle",
        extra={"in_window": sink.in_window, "written": written, "ok": error is None},
    )
    return written


def fire_new_ipo_context_pulls(
    data_dir: Path,
    new_ids: set[str],
    *,
    refresh_fn: Callable[[str, Path, str], str] | None = None,
) -> int:
    """For each newly-seen ``ipo_id``, fire one immediate single-symbol context pull.

    Dark-ships without ``UPSTOX_TOKEN`` (same posture as ``refresh_context.py`` itself — no token,
    no fetch, not an error). A single symbol's failure is logged and skipped; it never aborts the
    others or affects the records ingest that already completed. ``refresh_fn`` (injected for tests)
    returns a status — ``written`` / ``no_fields`` / ``symbol_not_listed`` — so each pull is logged
    with its cause, not a single ambiguous "empty". Returns how many pulls actually wrote context.
    """
    if not new_ids:
        return 0
    token = os.environ.get("UPSTOX_TOKEN", "").strip()
    if not token:
        _log.info("new_ipo_context_pull_darkship", extra={"new_ids": sorted(new_ids)})
        return 0
    fn = refresh_fn or _load_refresh_context().refresh_and_merge_one
    fired = 0
    for ipo_id in sorted(new_ids):
        symbol = ipo_id.upper()
        try:
            status = fn(token, data_dir, symbol)
        except Exception as exc:  # noqa: BLE001 — one symbol's failure must never abort the rest
            _log.warning("new_ipo_context_pull_failed", extra={"symbol": symbol, "error": str(exc)})
            continue
        if status == "written":
            fired += 1
            _log.info("new_ipo_context_pulled", extra={"symbol": symbol})
        elif status == "symbol_not_listed":
            _log.info("new_ipo_context_pull_symbol_not_listed", extra={"symbol": symbol})
        else:  # "no_fields" — resolved but the IPO carries no context fields yet
            _log.info("new_ipo_context_pull_no_fields", extra={"symbol": symbol})
    return fired


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one live NSE ingest into a data dir.")
    parser.add_argument(
        "--data-dir", required=True, help="the VM data dir (records + ingest_state)"
    )
    parser.add_argument("--env", default=None, help="environment (dev|prod)")
    args = parser.parse_args()

    config = load_config(env=args.env)
    data_dir = Path(args.data_dir)
    # v3-DP DP-1: log into the SAME `engine.log` family the V3-16 debug console reads
    # (`service/logs.py` globs engine.log[.1-.4]), instead of stderr-only as before — so the
    # recorder's structured events are durable, rotated and greppable rather than living only in
    # journald. Sole writer of this file on the VM (the engine process does not run here), so
    # there is no concurrent-rotation hazard. See the deploy note in operations/README.md about
    # what this does and does NOT buy: it does not make VM events appear in a desktop console.
    configure_logging(
        config.logging.level,
        json_output=config.logging.json_output,
        file_path=data_dir / "logs" / "engine.log",
    )
    count, new_ids = live_ingest_new_ids(build_nse(config, data_dir), data_dir)
    snap = IngestStateStore(data_dir / "ingest_state.json").current()
    _log.info("run_live_ingest_done", extra={"records": count, "ok": snap.last_attempt_ok})
    print(  # noqa: T201
        f"live ingest: {count} rec; ok={snap.last_attempt_ok}; last_success={snap.last_success}"
    )
    if new_ids:
        fired = fire_new_ipo_context_pulls(data_dir, new_ids)
        print(f"new IPOs: {sorted(new_ids)}; context pulls fired: {fired}")  # noqa: T201


if __name__ == "__main__":
    main()
