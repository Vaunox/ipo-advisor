"""Weekly local-fallback self-test CLI (v3 V3-4) — run it, record the verdict.

Deploy-side: a WEEKLY scheduled task (desktop, repo ``.venv`` Python) runs this. It builds the SAME
polite ``NseClient`` the live ingest uses (``config.scrape`` rate/UA discipline — one self-test/week
is trivial load) with an ISOLATED throwaway raw cache, drives the genuine local fallback (see
``ipo.service.fallback_selftest``), and writes the verdict to ``--out`` for
``run_heartbeat --fallback-selftest`` to surface.

    python scripts/fallback_selftest.py --out <path>/fallback_selftest.json [--env dev|prod]
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from ipo.core.config import load_config
from ipo.core.logging import configure_logging, get_logger
from ipo.data.sources.base import PoliteClient, RawCache
from ipo.data.sources.nse import NseClient
from ipo.service.fallback_selftest import run_fallback_selftest, write_selftest

_log = get_logger("ipo.service.fallback_selftest")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the weekly local-fallback self-test.")
    parser.add_argument("--out", required=True, help="where to write the verdict (JSON)")
    parser.add_argument("--env", default=None, help="environment (dev|prod)")
    args = parser.parse_args()

    config = load_config(env=args.env)
    configure_logging(config.logging.level, json_output=config.logging.json_output)

    # Same polite discipline as the live ingest (rate limit + UA); an ISOLATED raw cache so the
    # self-test touches nothing under the live data_store/. The cache dir is cleaned up regardless.
    cache_dir = Path(tempfile.mkdtemp(prefix="ipo-selftest-cache-"))
    try:
        client = PoliteClient(
            user_agent=config.scrape.user_agent,
            rate_limit_per_sec=config.scrape.rate_limit_per_sec,
            backoff_factor=config.scrape.backoff_factor,
            max_retries=config.scrape.max_retries,
            respect_robots=False,
        )
        nse = NseClient(client, RawCache(root=cache_dir))
        result = run_fallback_selftest(nse)
    finally:
        shutil.rmtree(cache_dir, ignore_errors=True)

    write_selftest(Path(args.out), result)
    _log.info("fallback_selftest", extra={"ok": result.ok, "records": result.records})
    print(f"fallback self-test: {'OK' if result.ok else 'FAILED'} - {result.detail}")  # noqa: T201


if __name__ == "__main__":
    main()
