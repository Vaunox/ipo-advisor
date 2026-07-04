"""Data-source freshness heartbeat (A4 part 4).

Reports the freshness of every persisted feed the app depends on — the market series,
the backfill, the shipped calibration artifacts, and the NSE holiday calendar — so a
silently-dead scraper or a calendar that has run off its edge is visible at a glance.
Staleness is a warning (some feeds are expected to be stale while their forward recorders
are deferred); only a missing required artifact is an error (non-zero exit).

Usage:
    python scripts/run_heartbeat.py
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

from ipo.core.calendar import latest_covered_year, now_ist, review_due
from ipo.service.heartbeat import (
    FeedHealth,
    any_missing,
    assess_feed,
    calendar_health,
    stale_feeds,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _max_date_in_column(path: Path, column: str) -> date | None:
    """Return the latest ISO date found in ``column`` of a CSV, or None."""
    if not path.is_file():
        return None
    latest: date | None = None
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            raw = (row.get(column) or "").strip()
            try:
                parsed = date.fromisoformat(raw)
            except ValueError:
                continue
            if latest is None or parsed > latest:
                latest = parsed
    return latest


def _mtime_date(path: Path) -> date | None:
    """The file's last-modified date (freshness proxy for built artifacts), or None."""
    return date.fromtimestamp(path.stat().st_mtime) if path.is_file() else None


def _collect(today: date) -> list[FeedHealth]:
    data = _REPO_ROOT / "data" / "backfill"
    models = _REPO_ROOT / "models"
    vix, nifty, backfill = data / "vix.csv", data / "nifty.csv", data / "mainboard_ipos.csv"
    calibrator, reliability = models / "calibrator.json", models / "reliability.json"
    return [
        assess_feed(
            "India VIX series (vix.csv)",
            present=vix.is_file(),
            data_through=_max_date_in_column(vix, "date"),
            today=today,
            max_age_days=7,
        ),
        assess_feed(
            "Nifty series (nifty.csv)",
            present=nifty.is_file(),
            data_through=_max_date_in_column(nifty, "date"),
            today=today,
            max_age_days=7,
        ),
        assess_feed(
            "Backfill (mainboard_ipos.csv)",
            present=backfill.is_file(),
            data_through=_max_date_in_column(backfill, "listing_date"),
            today=today,
            max_age_days=180,
        ),
        assess_feed(
            "Calibrator (models/calibrator.json)",
            present=calibrator.is_file(),
            data_through=_mtime_date(calibrator),
            today=today,
            max_age_days=120,  # quarterly recalibration ritual
            basis="last built",
        ),
        assess_feed(
            "Reliability (models/reliability.json)",
            present=reliability.is_file(),
            data_through=_mtime_date(reliability),
            today=today,
            max_age_days=120,
            basis="last built",
        ),
        calendar_health(latest_year=latest_covered_year(), review_due=review_due(today)),
    ]


def main() -> None:
    """Collect feed health and print the heartbeat; exit non-zero if a feed is missing."""
    argparse.ArgumentParser(description="Report data-source freshness (heartbeat).").parse_args()
    today = now_ist().date()
    feeds = _collect(today)

    lines = [f"data-source heartbeat @ {today.isoformat()}", ""]
    lines += [f"  [{f.status:<7}] {f.name} - {f.detail}" for f in feeds]
    stale = stale_feeds(feeds)
    missing = any_missing(feeds)
    lines.append("")
    if missing:
        lines.append("result: ERROR - a required artifact is MISSING")
    elif stale:
        lines.append(
            f"result: WARN - {len(stale)} feed(s) stale "
            "(expected while forward recorders are deferred; refresh on next run)"
        )
    else:
        lines.append("result: OK - all feeds fresh")

    print("\n".join(lines))  # noqa: T201
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
