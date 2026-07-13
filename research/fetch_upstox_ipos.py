"""Fetch Upstox IPO subscription data for the Check-1 field-definition comparison.

RESEARCH / OFF-MAIN. **You run this, not the assistant** — it authenticates to your
Upstox account with your Analytics Token, which is your action to take, not mine. The
token is read from a gitignored ``.env`` (or the ``UPSTOX_TOKEN`` env var) and is NEVER
printed, logged, or written to the output file. The output (``research/upstox_pull.json``)
contains only IPO market data — no secret — so it is safe to share back into the chat.

What it does (read-only GETs only, no order/trade endpoints touched):
  * GET https://api.upstox.com/v2/ipos?status=<listed|closed>
  * extracts, per IPO: name, symbol, status, bidding_end_date, total_subscription
  * writes them to research/upstox_pull.json and prints a table

Setup (one time):
    # in research/.env  (already gitignored via .env / .env.*)
    UPSTOX_TOKEN=your_analytics_token_here

Run:
    cd <repo root>
    .venv/Scripts/python.exe research/fetch_upstox_ipos.py
    # then paste the printed table (or let the assistant read research/upstox_pull.json)

If the token is missing/expired the script says so and exits non-zero; it never proceeds
without auth and never falls back to anything that would require a credential from me.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

_HOST = "https://api.upstox.com"
_STATUSES = ("listed", "closed")  # both carry a final (not live) total_subscription
_ISSUE_TYPE = "regular"  # mainboard only — our model excludes SME by design
_RECORDS = 30  # max page size per the SDK
_MAX_PAGES = 50  # safety cap on pagination
_OUT = Path(__file__).resolve().parent / "upstox_pull.json"
_FIELDS = ("name", "symbol", "status", "issue_type", "bidding_end_date", "total_subscription")
# Honest, descriptive client identity. The default `python-requests`/`python-urllib`
# User-Agent is on Cloudflare's error-1010 blocklist for this official developer API;
# this UA truthfully names the client (it is NOT a spoofed browser string).
_UA = "ipo-advisor-research/0.1 (authorized-analytics-token; read-only IPO data)"


def _read_text_any_encoding(path: Path) -> str:
    """Read text tolerant of the UTF-16/BOM that PowerShell's ``>`` writes on Windows."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _load_token() -> str:
    """Read UPSTOX_TOKEN from the environment or a local .env — never returned to logs."""
    import os

    token = os.environ.get("UPSTOX_TOKEN")
    if token:
        return token.strip()
    for env_path in (Path(__file__).resolve().parent / ".env", Path.cwd() / ".env"):
        if env_path.is_file():
            for line in _read_text_any_encoding(env_path).splitlines():
                line = line.strip()
                if line.startswith("UPSTOX_TOKEN") and "=" in line:
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    print(
        "ERROR: no token found. Put `UPSTOX_TOKEN=...` in research/.env "
        "(or export UPSTOX_TOKEN) and re-run.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _get(path: str, token: str) -> requests.Response:
    """Read-only GET to the fixed Upstox host with an honest client identity."""
    return requests.get(
        f"{_HOST}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": _UA,
            "Accept-Language": "en-IN,en;q=0.9",
        },
        timeout=30,
    )


def _rows_from_payload(payload: object) -> list[dict]:
    """Pull the IPO list out of whatever envelope the API returns (defensive)."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):  # e.g. {"data": {"ipos": [...]}}
            for v in data.values():
                if isinstance(v, list):
                    return [r for r in v if isinstance(r, dict)]
    return []


def _fetch_all_pages(token: str, status: str) -> list[dict]:
    """Page through one status filtered to mainboard (issue_type=regular), max 30/page."""
    rows: list[dict] = []
    for page in range(1, _MAX_PAGES + 1):
        path = (
            f"/v2/ipos?status={status}&issue_type={_ISSUE_TYPE}"
            f"&page_number={page}&records={_RECORDS}"
        )
        try:
            resp = _get(path, token)
        except requests.RequestException as exc:
            print(f"[{status} p{page}] network error: {exc}", file=sys.stderr)
            break
        if resp.status_code != 200:
            print(f"[{status} p{page}] HTTP {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
            break
        try:
            payload = resp.json()
        except ValueError:
            print(f"[{status} p{page}] non-JSON: {resp.text[:200]}", file=sys.stderr)
            break
        page_rows = _rows_from_payload(payload)
        rows.extend(page_rows)
        print(f"[{status} p{page}] {len(page_rows)} IPOs", file=sys.stderr)
        if len(page_rows) < _RECORDS:  # last page
            break
    return rows


def main() -> None:
    """Fetch all mainboard (regular) listed+closed IPOs; dump a token-free comparison file."""
    token = _load_token()
    collected: dict[str, dict] = {}
    for status in _STATUSES:
        for r in _fetch_all_pages(token, status):
            key = str(r.get("symbol") or r.get("name") or id(r))
            collected[key] = {k: r.get(k) for k in _FIELDS}

    ordered = sorted(
        collected.values(), key=lambda r: str(r.get("bidding_end_date") or ""), reverse=True
    )
    _OUT.write_text(json.dumps(ordered, indent=2, default=str), encoding="utf-8")

    print(f"\nWrote {len(ordered)} IPOs to {_OUT} (token-free — safe to share).\n")
    print(f"{'bidding_end':<12} {'status':<10} {'total_sub':>12}  name")
    print("-" * 72)
    for r in ordered[:40]:
        ts = r.get("total_subscription")
        ts_str = f"{ts}" if ts is not None else "—"
        print(
            f"{str(r.get('bidding_end_date') or '—'):<12} "
            f"{str(r.get('status') or '—'):<10} {ts_str:>12}  {r.get('name') or '—'}"
        )


if __name__ == "__main__":
    main()
