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

    python scripts/run_live_ingest.py --data-dir <vm-data> [--env dev|prod]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ipo.core.config import AppConfig, load_config
from ipo.core.logging import configure_logging, get_logger
from ipo.data.ingest.live import refresh_from_nse
from ipo.data.ingest.state import IngestStateStore
from ipo.data.sources.base import PoliteClient, RawCache
from ipo.data.sources.nse import NseClient
from ipo.data.store.repository import ParquetRepository

_log = get_logger("ipo.scripts.run_live_ingest")


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
    repo = ParquetRepository(data_dir)
    state = IngestStateStore(data_dir / "ingest_state.json")
    return refresh_from_nse(repo, nse, state=state)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one live NSE ingest into a data dir.")
    parser.add_argument(
        "--data-dir", required=True, help="the VM data dir (records + ingest_state)"
    )
    parser.add_argument("--env", default=None, help="environment (dev|prod)")
    args = parser.parse_args()

    config = load_config(env=args.env)
    configure_logging(config.logging.level, json_output=config.logging.json_output)
    data_dir = Path(args.data_dir)
    count = live_ingest(build_nse(config, data_dir), data_dir)
    snap = IngestStateStore(data_dir / "ingest_state.json").current()
    _log.info("run_live_ingest_done", extra={"records": count, "ok": snap.last_attempt_ok})
    print(  # noqa: T201
        f"live ingest: {count} rec; ok={snap.last_attempt_ok}; last_success={snap.last_success}"
    )


if __name__ == "__main__":
    main()
