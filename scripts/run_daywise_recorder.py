"""Run one day-wise subscription recording pass (v2 A1 — collect-forward).

Polls NSE's ``ipo-active-category`` for every open mainboard book and appends new,
timestamped subscription observations to the append-only bank under
``storage.daywise_dir``. This is the immediate, clock-dependent collect-forward action:
run it on a cadence NOW (e.g. cron every ~30 min, denser on issue-close day for the QIB
surge) so the day-by-day buildup history the trajectory candidate (v2 B1) needs actually
exists when that feature is eventually gated. Scheduler auto-wiring is a separate item (A2);
this script lets banking begin before then.

Append-only + idempotent: a poll that repeats the last banked observation is skipped, so
running it too often never duplicates. Nothing here touches the calibrated score.

Usage:
    python scripts/run_daywise_recorder.py
"""

from __future__ import annotations

from pathlib import Path

from ipo.core.config import load_config
from ipo.core.logging import configure_logging, get_logger
from ipo.data.ingest.daywise import record_daywise_subscription
from ipo.data.sources.base import PoliteClient, RawCache
from ipo.data.sources.nse import NseClient
from ipo.data.store.daywise import DaywiseSubscriptionStore

_REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """Run one recording pass and report how many observations were newly banked."""
    config = load_config()
    configure_logging(config.logging.level, json_output=config.logging.json_output)
    log = get_logger("ipo.scripts.run_daywise_recorder")

    client = PoliteClient(
        user_agent=config.scrape.user_agent,
        rate_limit_per_sec=2.0,  # polite but practical for a short poll of open books
        respect_robots=False,  # NSE disallows /api in robots; operator-authorized public data
        max_retries=config.scrape.max_retries,
    )
    cache = RawCache(root=_REPO_ROOT / config.ingest.raw_cache_dir)
    nse = NseClient(client, cache)
    store = DaywiseSubscriptionStore(_REPO_ROOT / config.storage.daywise_dir)

    banked = record_daywise_subscription(store, nse)
    log.info("daywise_pass_done", extra={"banked": banked})
    print(f"Day-wise recorder banked {banked} new subscription observation(s).")  # noqa: T201


if __name__ == "__main__":
    main()
