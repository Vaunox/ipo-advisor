"""Refresh the Allotment-tab registrar cache from Upstox (v3 V3-6). DISPLAY-ONLY DATA.

Writes ``<data-dir>/allotment/registrar_info.json`` — the token-free registrar cache the app's
Allotment tab reads. Registrar assignment is fixed when the RHP is filed and never changes, so this
is occasional reference data (run it like ``run_backfill``/``fetch_vix``, not on a live cadence).

**Runs anywhere — desktop OR the Part-II VM, unchanged.** It is deliberately self-contained: pure
Python + ``requests``, no ``ipo`` package import, no Windows/desktop assumption, token from the
environment, output path via ``--data-dir``. When the VM data layer lands it adopts this script
as-is as the (VM-primary) refresher for this feed; local execution is the fallback — one pattern.

Boundary (why this is safe): the app only READS the cache this writes; the registrar data lands in
a store entirely separate from ``IPORecord`` and can never reach a feature vector (import-graph
proven). This tool never touches an order/trade endpoint — read-only GETs to the IPO catalogue only.

Auth: reads ``UPSTOX_TOKEN`` from the environment (or a local ``.env`` beside this script / in CWD).
The token is NEVER printed, logged, or written to the output. The output is public IPO/registrar
business-contact data only — safe to share, commit, or sync to the app's data dir.

Run:
    UPSTOX_TOKEN=... python scripts/refresh_allotment.py --data-dir <the app's data dir>
    # dev default is ./data_store (the dev app's data dir); for the installed app pass the
    # per-user engine-data dir; for the VM pass the VM's data plane.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

_HOST = "https://api.upstox.com"
_STATUSES = ("closed", "listed")  # allotment-relevant lifecycle stages
_ISSUE_TYPE = "regular"  # mainboard only (SME excluded by the model's design)
_RECORDS = 30  # max page size
_MAX_PAGES = 50  # pagination safety cap
_DETAIL_PAUSE_S = 0.3  # polite delay between per-IPO detail GETs
# Honest client identity — the default python-requests UA is on this API's error-1010 blocklist;
# this truthfully names the client (NOT a spoofed browser string).
_UA = "ipo-advisor-allotment-refresh/1.0 (authorized-analytics-token; read-only IPO data)"
_REGISTRAR_FIELDS = ("name", "registrar", "website", "email", "contact_number", "contact_name")


def _read_text_any_encoding(path: Path) -> str:
    """Read text tolerant of the UTF-16/BOM a Windows shell ``>`` can write."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _load_token() -> str:
    """Read UPSTOX_TOKEN from the environment or a local .env — never returned to logs."""
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
        "ERROR: no token found. Set UPSTOX_TOKEN (env or a local .env) and re-run.", file=sys.stderr
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


def _rows(payload: object) -> list[dict]:
    """Pull the IPO list out of whatever envelope the API returns (defensive)."""
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    return [r for r in v if isinstance(r, dict)]
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    return []


def _list_ids(token: str) -> dict[str, object]:
    """Map upper(symbol) -> id across the allotment-relevant mainboard statuses."""
    ids: dict[str, object] = {}
    for status in _STATUSES:
        for page in range(1, _MAX_PAGES + 1):
            path = (
                f"/v2/ipos?status={status}&issue_type={_ISSUE_TYPE}"
                f"&page_number={page}&records={_RECORDS}"
            )
            resp = _get(path, token)
            if resp.status_code != 200:
                print(f"[list {status} p{page}] HTTP {resp.status_code}: {resp.text[:200]}",
                      file=sys.stderr)
                break
            rows = _rows(resp.json())
            for r in rows:
                sym = str(r.get("symbol", "")).upper()
                if sym and r.get("id") is not None:
                    ids[sym] = r["id"]
            if len(rows) < _RECORDS:
                break
    return ids


def _registrar(token: str, ipo_id: object) -> dict | None:
    """GET /v2/ipos/{id} and pull the registrar_info block (or None if absent/unreadable)."""
    resp = _get(f"/v2/ipos/{ipo_id}", token)
    if resp.status_code != 200:
        return None
    data = resp.json().get("data")
    obj = data if isinstance(data, dict) else (data[0] if isinstance(data, list) and data else None)
    if not isinstance(obj, dict):
        return None
    ri = obj.get("registrar_info")
    if not isinstance(ri, dict):
        return None
    picked = {k: ri.get(k) for k in _REGISTRAR_FIELDS if ri.get(k) not in (None, "")}
    # normalize the short code to `short` (the API calls it `registrar`); keep display `name`.
    if "registrar" in picked:
        picked["short"] = picked.pop("registrar")
    return picked or None


def main() -> None:
    """Fetch registrar_info across closed+listed mainboard IPOs; write the token-free cache."""
    parser = argparse.ArgumentParser(description="Refresh the Allotment-tab registrar cache.")
    parser.add_argument(
        "--data-dir",
        default="data_store",
        help="the app's data dir (dev default ./data_store; pass the installed app's per-user "
        "engine-data dir, or the VM's data plane)",
    )
    args = parser.parse_args()

    token = _load_token()
    ids = _list_ids(token)
    registrars: dict[str, dict] = {}
    for sym, ipo_id in sorted(ids.items()):
        info = _registrar(token, ipo_id)
        time.sleep(_DETAIL_PAUSE_S)
        if info:
            registrars[sym] = info

    out_dir = Path(args.data_dir) / "allotment"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "registrar_info.json"
    payload = {
        "refreshed_at": datetime.now(tz=UTC).astimezone().isoformat(),
        "registrars": registrars,
    }
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {len(registrars)} registrar entries to {out_path} (token-free).")
    for sym in list(registrars)[:8]:
        r = registrars[sym]
        nm = str(r.get("name") or r.get("short") or "—")[:34]
        print(f"  {sym:<12} {nm:<34} {r.get('website') or ''}")


if __name__ == "__main__":
    main()
