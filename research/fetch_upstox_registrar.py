"""V3-6 (Allotment tab) DATA-SHAPE probe — is Upstox's ``registrar_info`` real, populated, reliable?

RESEARCH / OFF-MAIN. **You run this, not the assistant** — it authenticates to your Upstox account
with your Analytics Token (read from a gitignored ``research/.env`` as ``UPSTOX_TOKEN``, or the env
var). The token is NEVER printed, logged, or written to the output. The output
(``research/upstox_registrar_check.json``) contains only public IPO market data — registrar
*business* contact info (name / support site / support email / phone), no user PII, no PAN, no
secret — so it is safe to share back into the chat.

Why: before designing an Allotment tab around ``registrar_info`` we must confirm it actually exists,
is populated across IPOs at/after the allotment stage, and looks trustworthy (real registrar names
like Link Intime / KFin / Bigshare, a plausible allotment-check URL). Check-1 taught us not to
assume an Upstox field is healthy — its ``total_subscription`` had endpoint-wide staleness. So this
measures coverage + eyeballs values rather than trusting the field.

What it does (read-only GETs only — no order/trade endpoints touched):
  * pages the mainboard list for the allotment-relevant statuses (closed, listed) -> symbol -> id
  * GETs /v2/ipos/{id} details for a capped, polite sample per status
  * SCHEMA DISCOVERY: records the union of top-level detail keys + 2 full sample detail objects, so
    we see the ACTUAL field names (registrar_info vs registrar vs …), not a guess
  * extracts the registrar fields per IPO and computes per-field coverage (non-null counts)
  * also records adjacent Part-IV fields (rhp_url/drhp_url/lot_size/isin/industry/cut_off_price)
    for free while we're on the details endpoint — reported, not yet acted on
  * writes research/upstox_registrar_check.json (token-free) and prints a coverage table

Run (from the repo root):
    .venv/Scripts/python.exe research/fetch_upstox_registrar.py
    # then let the assistant read research/upstox_registrar_check.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_upstox_ipos import (  # noqa: E402  (path shim above)
    _ISSUE_TYPE,
    _MAX_PAGES,
    _RECORDS,
    _get,
    _load_token,
    _rows_from_payload,
)

_OUT = Path(__file__).resolve().parent / "upstox_registrar_check.json"

# Allotment-relevant lifecycle: an IPO's registrar matters at/after the book closes (allotment +
# listing pending). These two statuses are exactly the tab's scope ("at/past the allotment stage").
_STATUSES = ("closed", "listed")
_SAMPLE_PER_STATUS = 20  # polite cap — enough to judge coverage without hammering the API
_DETAIL_PAUSE_S = 0.3  # be a polite client between per-IPO detail GETs

# Registrar field candidates (nested under registrar_info AND/OR flat) — the schema dump confirms
# which are real. Adjacent Part-IV context fields recorded but not acted on here.
_REGISTRAR_KEYS = (
    "name", "registrar", "website", "email", "contact_number", "contact_name", "phone",
)  # fmt: skip
_ADJACENT_KEYS = (
    "rhp_url", "drhp_url", "lot_size", "isin", "industry", "cut_off_price", "status",
)  # fmt: skip


def _pull_list(token: str) -> list[dict]:
    """List rows across the allotment-relevant statuses: {symbol, id, name, status}."""
    rows: list[dict] = []
    for status in _STATUSES:
        got = 0
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
            page_rows = _rows_from_payload(resp.json())
            for r in page_rows:
                rows.append({
                    "symbol": str(r.get("symbol", "")).upper(),
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "status": status,
                })
            got += len(page_rows)
            if len(page_rows) < _RECORDS or got >= _SAMPLE_PER_STATUS:
                break
    return rows


def _detail_obj(token: str, ipo_id: object) -> dict | None:
    """GET /v2/ipos/{id} and return the data object (or None on error)."""
    resp = _get(f"/v2/ipos/{ipo_id}", token)
    if resp.status_code != 200:
        return None
    data = resp.json().get("data")
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return None


def _extract_registrar(obj: dict) -> dict:
    """Pull registrar fields — from a nested ``registrar_info`` dict and/or flat top-level keys.

    Records ``has_registrar_info_object`` so the report distinguishes a real nested object from
    values scavenged off the top level.
    """
    ri = obj.get("registrar_info")
    src: dict = ri if isinstance(ri, dict) else {}
    out: dict = {"has_registrar_info_object": isinstance(ri, dict)}
    for k in _REGISTRAR_KEYS:
        out[k] = src.get(k) if src.get(k) is not None else obj.get(k)
    return out


def main() -> None:
    """Probe registrar_info coverage across a polite sample; write a token-free report."""
    token = _load_token()
    listing = _pull_list(token)
    # cap per status
    sample: list[dict] = []
    seen: dict[str, int] = {s: 0 for s in _STATUSES}
    for row in listing:
        s = row["status"]
        if seen.get(s, 0) < _SAMPLE_PER_STATUS and row["id"] is not None:
            sample.append(row)
            seen[s] += 1

    key_union: set[str] = set()
    full_samples: list[dict] = []
    per_ipo: list[dict] = []
    for row in sample:
        obj = _detail_obj(token, row["id"])
        time.sleep(_DETAIL_PAUSE_S)
        if obj is None:
            base = {k: row[k] for k in ("symbol", "name", "status")}
            per_ipo.append({**base, "error": "no details"})
            continue
        key_union |= set(obj.keys())
        if len(full_samples) < 2:  # 2 full detail objects for schema visibility (public data)
            full_samples.append(obj)
        reg = _extract_registrar(obj)
        adjacent = {k: obj.get(k) for k in _ADJACENT_KEYS}
        per_ipo.append({
            "symbol": row["symbol"], "name": row["name"], "status": row["status"],
            "registrar": reg, "adjacent": adjacent,
        })

    # coverage: non-null counts per registrar field, overall and per status
    def _coverage(keys: tuple[str, ...], picker) -> dict:
        cov: dict = {}
        rows = [r for r in per_ipo if "registrar" in r]
        for k in keys:
            n = sum(1 for r in rows if picker(r).get(k) not in (None, "", []))
            cov[k] = f"{n}/{len(rows)}"
        return cov

    summary = {
        "sampled": len(per_ipo),
        "by_status": {s: sum(1 for r in per_ipo if r.get("status") == s) for s in _STATUSES},
        "detail_key_union": sorted(key_union),
        "registrar_coverage": _coverage(_REGISTRAR_KEYS, lambda r: r["registrar"]),
        "adjacent_coverage": _coverage(_ADJACENT_KEYS, lambda r: r["adjacent"]),
    }
    _OUT.write_text(
        json.dumps({"summary": summary, "full_detail_samples": full_samples, "per_ipo": per_ipo},
                   indent=2, default=str),
        encoding="utf-8",
    )

    print(f"\nWrote {_OUT} (token-free — safe to share).\n")
    print(f"sampled {summary['sampled']} IPOs  {summary['by_status']}")
    print("\nregistrar field coverage (non-null / sampled):")
    for k, v in summary["registrar_coverage"].items():
        print(f"  registrar.{k:<16} {v}")
    print("\nadjacent Part-IV field coverage:")
    for k, v in summary["adjacent_coverage"].items():
        print(f"  {k:<16} {v}")
    print("\ndetail top-level keys seen:", ", ".join(summary["detail_key_union"]) or "(none)")
    print("\nsample registrar values:")
    for r in per_ipo[:8]:
        reg = r.get("registrar", {})
        nm = reg.get("name") or reg.get("registrar") or "—"
        print(f"  {r.get('symbol', ''):<12} name={str(nm):<22} "
              f"site={str(reg.get('website') or '—')[:40]}")


if __name__ == "__main__":
    main()
