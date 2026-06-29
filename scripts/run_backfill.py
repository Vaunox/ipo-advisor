"""Backfill the >=100-IPO calibration sample from official NSE data (Phase 4 prereq).

Pulls the NSE past-issues master list, filters to mainboard issues since the
configured start, and for each fetches official subscription (QIB/NII/retail) and the
listing-day open/close (bhavcopy). Writes a committed CSV in the seed schema so the
calibration is reproducible and the existing pipeline can ingest it.

Polite + resumable: every response is cached immutably, so re-running (or resuming
after a timeout) re-reads rather than re-fetches. Optional enrichment (issue P/E,
OFS, peer P/E, anchor) is added by a separate pass; missing values stay blank
(the model drops optional features) and are never fabricated.

Usage:
    python scripts/run_backfill.py [--start-year 2021] [--limit N] [--out PATH]
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

from ipo.core.config import load_config
from ipo.core.logging import configure_logging, get_logger
from ipo.data.sources.base import PoliteClient, RawCache, SourceError
from ipo.data.sources.nse import NseClient, mainboard_since

_REPO_ROOT = Path(__file__).resolve().parents[1]

_COLUMNS = [
    "ipo_id", "name", "segment", "price_band_low", "price_band_high",
    "lot_size", "issue_size_cr", "ofs_fraction", "open_date", "close_date",
    "listing_date", "qib_sub", "nii_sub", "retail_sub", "issue_pe",
    "peer_median_pe", "promoter_litigation", "listing_open", "listing_close",
]  # fmt: skip


def main() -> None:
    """Run the official NSE backfill and write the seed-schema CSV."""
    parser = argparse.ArgumentParser(description="Backfill mainboard IPOs from NSE.")
    parser.add_argument("--start-year", type=int, default=2021)
    parser.add_argument("--limit", type=int, default=None, help="cap issues (for testing)")
    parser.add_argument("--out", default="data/backfill/mainboard_ipos.csv")
    parser.add_argument(
        "--max-retries", type=int, default=None, help="override retry count (fast-skip throttled)"
    )
    args = parser.parse_args()

    config = load_config()
    configure_logging(config.logging.level, json_output=config.logging.json_output)
    log = get_logger("ipo.scripts.run_backfill")

    client = PoliteClient(
        user_agent=config.scrape.user_agent,
        rate_limit_per_sec=2.0,  # polite but practical for a one-time bulk pull
        respect_robots=False,  # NSE disallows /api in robots; operator-authorized public data
        max_retries=args.max_retries or config.scrape.max_retries,
    )
    cache = RawCache(root=_REPO_ROOT / config.ingest.raw_cache_dir)
    nse = NseClient(client, cache)

    start = date(args.start_year, 1, 1)
    issues = mainboard_since(nse.past_issues(), start)
    issues.sort(key=lambda i: i.listing_date or date.min)
    if args.limit:
        issues = issues[: args.limit]
    log.info("backfill_start", extra={"candidates": len(issues), "since": start.isoformat()})

    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    skipped = 0
    for i, issue in enumerate(issues, 1):
        if issue.price_band_high is None or issue.listing_date is None:
            skipped += 1
            continue
        ipo_id = f"{issue.symbol}-{issue.listing_date.isoformat()}"
        if ipo_id in seen:
            skipped += 1  # NSE sometimes lists a symbol twice; keep the first
            continue
        try:
            sub = nse.subscription(issue.symbol)
            prices = nse.listing_prices(issue.symbol, issue.listing_date)
        except SourceError as exc:
            log.warning("backfill_skip", extra={"symbol": issue.symbol, "error": str(exc)})
            skipped += 1
            continue
        if prices is None:
            skipped += 1  # not listed on NSE (e.g. BSE-only) -> no label
            continue
        open_px, close_px = prices
        open_d = issue.open_date or issue.close_date
        close_d = issue.close_date or issue.open_date
        seen.add(ipo_id)
        rows.append(
            {
                "ipo_id": ipo_id,
                "name": issue.company,
                "segment": issue.segment,
                "price_band_low": issue.price_band_low or issue.price_band_high,
                "price_band_high": issue.price_band_high,
                "lot_size": "",
                "issue_size_cr": "",
                "ofs_fraction": "",
                "open_date": open_d.isoformat() if open_d else "",
                "close_date": close_d.isoformat() if close_d else "",
                "listing_date": issue.listing_date.isoformat(),
                "qib_sub": sub.qib if sub.qib is not None else "",
                "nii_sub": sub.nii if sub.nii is not None else "",
                "retail_sub": sub.retail if sub.retail is not None else "",
                "issue_pe": "",
                "peer_median_pe": "",
                "promoter_litigation": "false",
                "listing_open": open_px,
                "listing_close": close_px,
            }
        )
        if i % 25 == 0:
            log.info("backfill_progress", extra={"done": i, "kept": len(rows)})

    out_path = _REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    log.info("backfill_done", extra={"written": len(rows), "skipped": skipped})
    print(f"Backfill wrote {len(rows)} IPOs to {args.out} ({skipped} skipped).")  # noqa: T201


if __name__ == "__main__":
    main()
