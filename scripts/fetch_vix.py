"""Backfill India VIX daily history into data/backfill/vix.csv (v2 B2 — VIX flag-enrichment).

One-time / on-demand backfill (like ``scripts/run_backfill.py``), **not** a standing recorder — so
it is not subject to the forward-recording deferral (Part I-A). India VIX is a free,
point-in-time-clean daily series; here it feeds the regime **cold-market flag only** (weight 0,
annotation), so Yahoo Finance (``^INDIAVIX``) is an adequate source — the flag never touches the
calibrated probability, so the data-trust boundary (which governs *calibration-critical* fields)
does not require NSE-official. If B2's gated **score-feature** half is ever pursued, cross-check
against NSE's official historical VIX first.

Yahoo's ``range=max`` call downsamples to ~monthly, so we fetch in short (per-year) windows to keep
**daily** resolution, then merge **append-only** — a stored close is never mutated, preserving the
point-in-time invariant (a later refresh can only add new dates).

Usage:
    python scripts/fetch_vix.py
"""

from __future__ import annotations

import csv
import datetime as dt
import time
from pathlib import Path

import requests

_ROOT = Path(__file__).resolve().parents[1]
_OUT = _ROOT / "data" / "backfill" / "vix.csv"
_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5EINDIAVIX"
_START_YEAR = 2008  # India VIX history on Yahoo begins Apr 2008


def _fetch_year(year: int) -> list[tuple[dt.date, float]]:
    """Fetch one calendar year of daily (date, close) points from Yahoo (empty on failure)."""
    p1 = int(dt.datetime(year, 1, 1).timestamp())
    p2 = int(dt.datetime(year + 1, 1, 1).timestamp())
    params: dict[str, int | str] = {"period1": p1, "period2": p2, "interval": "1d"}
    resp = requests.get(
        _URL,
        params=params,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()["chart"]["result"][0]
    stamps = result.get("timestamp") or []
    closes = result["indicators"]["quote"][0].get("close") or []
    out: list[tuple[dt.date, float]] = []
    for stamp, close in zip(stamps, closes, strict=False):
        if close is None:
            continue
        out.append((dt.datetime.fromtimestamp(stamp).date(), round(float(close), 2)))
    return out


def main() -> None:
    """Fetch India VIX daily closes and write/refresh vix.csv (append-only, sorted)."""
    by_date: dict[dt.date, float] = {}
    if _OUT.is_file():  # append-only: keep every stored close, add only new dates
        with _OUT.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                by_date[dt.date.fromisoformat(row["date"])] = float(row["close"])

    added = 0
    for year in range(_START_YEAR, dt.date.today().year + 1):
        for day, close in _fetch_year(year):
            if day not in by_date:
                by_date[day] = close
                added += 1
        time.sleep(0.3)  # polite pacing

    rows = sorted(by_date.items())
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    with _OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "close"])
        for day, close in rows:
            writer.writerow([day.isoformat(), close])

    span = f"{rows[0][0]}..{rows[-1][0]}" if rows else "empty"
    print(f"vix.csv: {len(rows)} rows ({span}), {added} new")  # noqa: T201


if __name__ == "__main__":
    main()
