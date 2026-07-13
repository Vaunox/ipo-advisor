"""Check 1 CONTROL — is OUR OWN backfill CSV stale, or genuinely NSE-final?

RESEARCH / OFF-MAIN, read-only, PUBLIC data (no token, no personal account — NSE's IPO endpoints are
unauthenticated JSON APIs; this project already scrapes them for the shipped backfill, see
``src/ipo/data/sources/nse.py`` / ``scripts/run_backfill.py``, `respect_robots=False`, "operator-
authorized public data"). The assistant runs this one directly.

Why this exists: ``RawCache`` is write-once-immutable (never mutated after first store). The
backfill script's ``nse.subscription(symbol)`` call defaults to ``force=False``, which reads the
cache if present. So if a symbol's subscription was cached *before* NSE's own number fully settled,
our backfill CSV could be frozen on a stale value too — undermining the "our data is right, Upstox
is wrong" conclusion from Check 1. This script re-fetches subscription for target symbols **live,
bypassing the cache entirely** (``force=True``) and reports fresh-NSE vs our backfill CSV vs
Upstox, so we know which (if either) is actually stale.

Usage: PYTHONPATH=src python research/fetch_nse_fresh.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from ipo.core.config import load_config
from ipo.data.sources.base import PoliteClient, RawCache, SourceError
from ipo.data.sources.nse import NseClient

_REPO = Path(__file__).resolve().parents[1]
_CSV = _REPO / "data" / "backfill" / "mainboard_ipos.csv"
_UPSTOX_PULL = _REPO / "research" / "upstox_pull.json"

# NSE symbol -> our backfill CSV name-fragment, for the suspects + controls from the earlier checks.
_TARGETS = {
    "MEESHO": "Meesho",
    "BHARATCOAL": "Bharat Coking Coal",
    "CORONA": "Corona Remedies",
    "SWIGGY": "Swiggy",
    "VMM": "Vishal Mega Mart",
    "SANATHAN": "Sanathan Textiles",
    "DAMCAPITAL": "DAM Capital",
    "TRANSRAILL": "Transrail Lighting",
    "EIEL": "Enviro Infra",
    "SENORES": "Senores Pharmaceuticals",
    "CMRGREEN": "CMR Green",
    "TURTLEMINT": "Turtlemint",
    "RUBICON": "Rubicon Research",
    "LENSKART": "Lenskart",
}

# Mainboard Upstox rows closing on/after the API's announced launch date (2026-05-23) that are
# NOT yet in our static backfill CSV -- fetched by symbol directly (no CSV name-match needed).
_POST_LAUNCH_NOT_IN_CSV = {
    "LASERPOWER": "Laser Power & Infra",
    "KUSUMGAR": "Kusumgar",
    "KNACK": "Knack Packaging",
    "AASTHA": "Aastha Spintex",
    "CSM": "CSM Technologies",
    "RAMBHAJO": "Advit Jewels",
    "CORDELIA": "Waterways Leisure Tourism",
    "HEXAGON": "Hexagon Nutrition",
}


def _load_csv_by_name_fragment() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with _CSV.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows[r["name"]] = r
    return rows


def _find_csv_row(csv_rows: dict[str, dict], fragment: str) -> dict | None:
    for name, row in csv_rows.items():
        if fragment.lower() in name.lower():
            return row
    return None


def _load_upstox_by_symbol() -> dict[str, dict]:
    data = json.loads(_UPSTOX_PULL.read_text(encoding="utf-8"))
    return {str(r.get("symbol", "")).upper(): r for r in data}


def main() -> None:
    """Fetch fresh (cache-bypassing) NSE subscription and compare vs our CSV vs Upstox."""
    config = load_config()
    client = PoliteClient(
        user_agent=config.scrape.user_agent,
        rate_limit_per_sec=2.0,
        respect_robots=False,  # operator-authorized public data, same as shipped backfill/live
        max_retries=config.scrape.max_retries,
    )
    cache = RawCache(root=_REPO / config.ingest.raw_cache_dir)
    nse = NseClient(client, cache)

    csv_rows = _load_csv_by_name_fragment()
    upstox_rows = _load_upstox_by_symbol()

    print(f"{'symbol':<12}{'fresh_nse':>12}{'our_csv':>12}{'upstox':>12}  name")
    print("-" * 80)
    results = []
    for symbol, fragment in _TARGETS.items():
        try:
            sub = nse.subscription(symbol, force=True)  # bypass cache -- live fetch, right now
        except SourceError as exc:
            print(f"{symbol:<12}{'ERROR':>12}  {exc}")
            continue
        csv_row = _find_csv_row(csv_rows, fragment)
        our_val = csv_row["total_sub"] if csv_row else None
        ups_val = upstox_rows.get(symbol, {}).get("total_subscription")
        fresh = sub.total
        results.append(
            {"symbol": symbol, "fresh_nse": fresh, "our_csv": our_val, "upstox": ups_val}
        )
        f_str = f"{fresh:.2f}" if fresh is not None else "—"
        o_str = f"{float(our_val):.2f}" if our_val else "—"
        u_str = f"{float(ups_val):.2f}" if ups_val else "—"
        print(f"{symbol:<12}{f_str:>12}{o_str:>12}{u_str:>12}  {fragment}")

    # Post-launch-only rows (not in our CSV yet): fetch fresh NSE directly, compare vs Upstox.
    # This is the operator's launch-date hypothesis test with a real N instead of N=2.
    print("\n(post-launch, not yet in our CSV)")
    print(f"{'symbol':<12}{'fresh_nse':>12}{'upstox':>12}{'pct%':>8}  name")
    print("-" * 88)
    post_launch_results = []
    for symbol, fragment in _POST_LAUNCH_NOT_IN_CSV.items():
        try:
            sub = nse.subscription(symbol, force=True)
        except SourceError as exc:
            print(f"{symbol:<12}{'ERROR':>12}  {exc}")
            continue
        ups_val = upstox_rows.get(symbol, {}).get("total_subscription")
        fresh = sub.total
        pct = None
        if fresh is not None and ups_val is not None and float(ups_val) != 0:
            pct = 100.0 * (float(ups_val) - fresh) / fresh
        post_launch_results.append(
            {"symbol": symbol, "fresh_nse": fresh, "upstox": ups_val, "pct_diff": pct}
        )
        f_str = f"{fresh:.2f}" if fresh is not None else "—"
        u_str = f"{float(ups_val):.2f}" if ups_val else "—"
        p_str = f"{pct:+.1f}" if pct is not None else "—"
        print(f"{symbol:<12}{f_str:>12}{u_str:>12}{p_str:>8}  {fragment}")

    out2 = _REPO / "research" / "nse_fresh_post_launch.json"
    out2.write_text(json.dumps(post_launch_results, indent=2), encoding="utf-8")
    print(f"\nWrote {out2}")

    with_pct = [r for r in post_launch_results if r["pct_diff"] is not None]
    clean = [r for r in with_pct if abs(r["pct_diff"]) <= 2]
    dirty = [r for r in with_pct if abs(r["pct_diff"]) > 2]
    print(f"\npost-launch clean(<=2%): {len(clean)}   dirty(>2%): {len(dirty)}   "
          f"of {len(post_launch_results)} tested")
    if dirty:
        print("dirty symbols:", ", ".join(f"{r['symbol']}({r['pct_diff']:+.1f}%)" for r in dirty))

    out = _REPO / "research" / "nse_fresh_check.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")

    # Summary: does fresh NSE match our CSV (validating it), or drift from it (flagging staleness)?
    print("\n--- does fresh NSE confirm our backfill CSV? ---")
    for r in results:
        if r["fresh_nse"] is None or r["our_csv"] is None:
            continue
        diff_pct = 100.0 * (r["fresh_nse"] - float(r["our_csv"])) / float(r["our_csv"])
        flag = "MATCH" if abs(diff_pct) < 1.0 else "DRIFT"
        print(f"{r['symbol']:<12} fresh vs our_csv: {diff_pct:+.2f}%  [{flag}]")


if __name__ == "__main__":
    main()
