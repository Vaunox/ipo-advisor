"""Check 1 RE-CONFIRM — is Upstox's DETAILS endpoint fresher than the LIST endpoint?

RESEARCH / OFF-MAIN. Operator runs it (authenticated); assistant reads only the token-free output.
Question: for IPOs where the list `/v2/ipos` total_subscription looked stale vs our NSE final, does
the details `/v2/ipos/{id}` carry a different (fresher) value, or the same stale one?

Pulls the mainboard list once (symbol -> id + list total), then GETs details for a fixed set of
targets (stale suspects + clean controls), recording the details total_subscription. Writes
research/upstox_details_check.json (token-free). Run like fetch_upstox_ipos.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_upstox_ipos import (  # noqa: E402  (path shim above)
    _ISSUE_TYPE,
    _MAX_PAGES,
    _RECORDS,
    _STATUSES,
    _get,
    _load_token,
    _rows_from_payload,
)

_OUT = Path(__file__).resolve().parent / "upstox_details_check.json"

# Symbols from the earlier list pull. Suspects = big list-vs-our-NSE gaps (list understated);
# controls = near-perfect list matches. If details == our final for the suspects, the API is usable
# via details; if details == the stale list value, the staleness is endpoint-wide.
_SUSPECTS = {
    "MEESHO", "BHARATCOAL", "CORONA", "SWIGGY", "VMM", "SANATHAN",
    "DAMCAPITAL", "TRANSRAILL", "EIEL", "SENORES",
}  # fmt: skip
_CONTROLS = {"KUSUMGAR", "CMRGREEN", "TURTLEMINT", "RUBICON", "LENSKART"}
_TARGETS = _SUSPECTS | _CONTROLS


def _pull_list(token: str) -> dict[str, dict]:
    """Map upper(symbol) -> {id, name, list_total} across all mainboard list pages."""
    by_symbol: dict[str, dict] = {}
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
            rows = _rows_from_payload(resp.json())
            for r in rows:
                sym = str(r.get("symbol", "")).upper()
                by_symbol[sym] = {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "list_total": r.get("total_subscription"),
                }
            if len(rows) < _RECORDS:
                break
    return by_symbol


def _fetch_detail(token: str, ipo_id: object) -> dict:
    """GET /v2/ipos/{id} and pull the details total_subscription (+ status)."""
    resp = _get(f"/v2/ipos/{ipo_id}", token)
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:150]}"}
    data = resp.json().get("data")
    obj = None
    if isinstance(data, dict):
        obj = data
    elif isinstance(data, list) and data and isinstance(data[0], dict):
        obj = data[0]
    if obj is None:
        return {"error": "no data object in details response"}
    return {"details_total": obj.get("total_subscription"), "detail_status": obj.get("status")}


def main() -> None:
    """Compare list vs details total_subscription for the target IPOs; dump token-free JSON."""
    token = _load_token()
    by_symbol = _pull_list(token)
    out: list[dict] = []
    for sym in sorted(_TARGETS):
        info = by_symbol.get(sym)
        if info is None:
            out.append({"symbol": sym, "error": "not found in list"})
            continue
        detail = _fetch_detail(token, info["id"]) if info["id"] is not None else {"error": "no id"}
        out.append(
            {
                "symbol": sym,
                "name": info["name"],
                "id": info["id"],
                "kind": "suspect" if sym in _SUSPECTS else "control",
                "list_total": info["list_total"],
                **detail,
            }
        )
    _OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")

    print(f"\nWrote {_OUT} (token-free — safe to share).\n")
    print(f"{'symbol':<12}{'kind':<9}{'list_total':>12}{'details_total':>15}  name")
    print("-" * 78)
    for r in out:
        lt = r.get("list_total", "—")
        dt = r.get("details_total", r.get("error", "—"))
        print(f"{r['symbol']:<12}{r.get('kind', '—'):<9}{str(lt):>12}{str(dt):>15}  "
              f"{str(r.get('name', ''))[:28]}")


if __name__ == "__main__":
    main()
