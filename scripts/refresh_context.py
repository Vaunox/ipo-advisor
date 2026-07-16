"""Refresh the per-IPO Upstox context cache (v3 V3-5/V3-6+). DISPLAY-ONLY DATA.

Writes ``<data-dir>/context/ipo_context.json`` — the ONE token-free cache the app reads for every
per-IPO Upstox *details* field it surfaces: the registrar (Allotment tab, V3-6), the RHP link
(detail page, V3-5), and later lot_size / isin / anchor (V3-8/11/10). One store, one refresh, one
staleness rule — not a separate cache per feature. Adding a field is a couple of lines here + store.

These fields are fixed once filed, so this is occasional reference data — run it like
``run_backfill`` / ``fetch_vix`` (e.g. when new IPOs appear), not on a live cadence.

**Runs anywhere — desktop OR the Part-II VM, unchanged.** Deliberately self-contained: pure Python +
``requests``, no ``ipo`` import, no Windows/desktop assumption, token from the environment, output
path via ``--data-dir``. When the VM data layer lands it adopts this script as-is as the VM-primary
refresher; local execution is the fallback — one data pattern.

Boundary: the app only READS what this writes; the context lands in a store separate from
``IPORecord`` and can never reach a feature vector (import-graph proven). Read-only GETs to the IPO
catalogue only — never an order/trade endpoint.

Auth: reads ``UPSTOX_TOKEN`` from the environment (or a local ``.env`` beside this script / in CWD).
The token is NEVER printed, logged, or written to the output. Output is public IPO business data.

Run:
    UPSTOX_TOKEN=... python scripts/refresh_context.py --data-dir <the app's data dir>
    # dev default is ./data_store; installed app: the per-user engine-data dir; VM: its data plane.
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
# RHP first appears at 'open' (probe finding), so we cover open→closed→listed. 'upcoming' IPOs have
# no symbol and no RHP — unjoinable, so they're excluded at ingest (never filtered at a call site).
_STATUSES = ("open", "closed", "listed")
_ISSUE_TYPE = "regular"  # mainboard only (SME excluded by the model's design)
_RECORDS = 30
_MAX_PAGES = 50
_DETAIL_PAUSE_S = 0.3
# Honest client identity — the default python-requests UA is on this API's error-1010 blocklist.
_UA = "ipo-advisor-context-refresh/1.0 (authorized-analytics-token; read-only IPO data)"
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


def _rows(payload: object) -> list[dict[str, object]]:
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
    """Map upper(symbol) -> id across open+closed+listed. Blank-symbol IPOs are dropped here."""
    ids: dict[str, object] = {}
    for status in _STATUSES:
        for page in range(1, _MAX_PAGES + 1):
            path = (
                f"/v2/ipos?status={status}&issue_type={_ISSUE_TYPE}"
                f"&page_number={page}&records={_RECORDS}"
            )
            resp = _get(path, token)
            if resp.status_code != 200:
                print(
                    f"[list {status} p{page}] HTTP {resp.status_code}: {resp.text[:200]}",
                    file=sys.stderr,
                )
                break
            rows = _rows(resp.json())
            for r in rows:
                sym = str(r.get("symbol") or "").strip().upper()
                if sym and sym != "NONE" and r.get("id") is not None:  # exclude symbol-less IPOs
                    ids.setdefault(sym, r["id"])  # first (open) wins over later duplicates
            if len(rows) < _RECORDS:
                break
    return ids


def _context(token: str, ipo_id: object) -> dict[str, object]:
    """GET /v2/ipos/{id} and pull the per-IPO context fields (registrar + rhp_url).

    A fetch FAILURE (non-200 / malformed body) prints to stderr before returning ``{}`` — otherwise
    it is indistinguishable from an IPO that genuinely has no registrar/RHP yet. Package-free
    script, so stderr → journald is the honest channel (matching ``_list_ids``).
    """
    resp = _get(f"/v2/ipos/{ipo_id}", token)
    if resp.status_code != 200:
        print(f"[context id={ipo_id}] HTTP {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
        return {}
    data = resp.json().get("data")
    obj = data if isinstance(data, dict) else (data[0] if isinstance(data, list) and data else None)
    if not isinstance(obj, dict):
        print(f"[context id={ipo_id}] malformed detail body (no data object)", file=sys.stderr)
        return {}
    entry: dict[str, object] = {}
    ri = obj.get("registrar_info")
    if isinstance(ri, dict):
        reg = {k: ri.get(k) for k in _REGISTRAR_FIELDS if ri.get(k) not in (None, "")}
        if "registrar" in reg:
            reg["short"] = reg.pop("registrar")  # the API's short code -> our `short`
        if reg:
            entry["registrar"] = reg
    rhp = obj.get("rhp_url")  # Red Herring Prospectus (final offer doc); DRHP dropped (unusable)
    if rhp:
        entry["rhp_url"] = rhp
    lot = obj.get("lot_size")  # bid lot — NSE gives it on 0% of IPOs, so Upstox is the sole source
    if isinstance(lot, int) and lot > 0:
        entry["lot_size"] = lot
    elif isinstance(lot, str) and lot.strip().isdigit() and int(lot) > 0:
        entry["lot_size"] = int(lot)
    for key in ("isin", "industry"):  # V3-11 reference fields — plain display metadata
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            entry[key] = val.strip()
    return entry


def _resolve_and_fetch(token: str, symbol: str) -> tuple[str, dict[str, object]]:
    """Resolve one symbol's Upstox id and fetch its context, distinguishing WHY nothing came back.

    Returns ``(status, entry)`` where status is ``"symbol_not_listed"`` (no such symbol in Upstox's
    open/closed/listed listing yet) or ``"ok"`` (resolved; ``entry`` may still be empty if the IPO
    genuinely carries no context fields). The onset trigger uses this split so the log can name the
    cause instead of a single ambiguous "empty".
    """
    ids = _list_ids(token)
    ipo_id = ids.get(symbol.upper())
    if ipo_id is None:
        return "symbol_not_listed", {}
    return "ok", _context(token, ipo_id)


def refresh_one(token: str, symbol: str) -> dict[str, object]:
    """Resolve one symbol's Upstox id (from the open/closed/listed listing) and fetch its context.

    Used for the new-IPO onset trigger: a single symbol detected by the NSE ingest, not the full
    universe. Still pages the listing once (cheap; no per-IPO detail fetch) to resolve the id, then
    makes exactly one detail call — the slow part (the ``_DETAIL_PAUSE_S``-paced per-IPO loop) is
    what this avoids doing for every other already-known symbol.
    """
    return _resolve_and_fetch(token, symbol)[1]


def merge_context(data_dir: Path, symbol: str, entry: dict[str, object]) -> bool:
    """Merge one symbol's context entry into the cache, leaving every other entry untouched.

    Deliberately does NOT advance the top-level ``refreshed_at`` — that timestamp is the ONE
    staleness signal every field's ``field_state`` trusts (ipo_context.py). Bumping it here would
    imply every OTHER cached IPO was just rechecked, which is false and would understate their true
    staleness. A present field displays correctly regardless of ``refreshed_at`` (only an absent one
    consults it), so the onset-gap fix works without that timestamp moving. Returns whether the
    cache was written (``False`` when ``entry`` is empty — nothing to add yet).
    """
    if not entry:
        return False
    out_path = Path(data_dir) / "context" / "ipo_context.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.is_file():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # An existing cache that won't parse: do NOT reset it to a single entry (that would
            # wipe every OTHER IPO's context). Refuse the merge and leave the file for inspection.
            print(
                f"[merge {symbol}] existing cache unreadable — refusing to overwrite: {exc}",
                file=sys.stderr,
            )
            return False
    else:
        existing = {}
    refreshed_at = existing.get("refreshed_at") if isinstance(existing, dict) else None
    ipos = existing.get("ipos") if isinstance(existing, dict) else None
    ipos = dict(ipos) if isinstance(ipos, dict) else {}
    ipos[symbol.upper()] = entry
    payload = {"refreshed_at": refreshed_at, "ipos": ipos}
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(out_path)
    return True


def refresh_and_merge_one(token: str, data_dir: Path, symbol: str) -> str:
    """The onset-trigger entry point: fetch one symbol's context and merge it.

    Returns a status naming the outcome — ``"written"`` (merged into the cache), ``"no_fields"``
    (resolved, but the IPO carries no context yet), or ``"symbol_not_listed"`` (Upstox's listing has
    no such symbol yet) — so the caller can log WHY an onset pull produced nothing, not merely that
    it did.
    """
    status, entry = _resolve_and_fetch(token, symbol)
    if status == "symbol_not_listed":
        return "symbol_not_listed"
    return "written" if merge_context(data_dir, symbol, entry) else "no_fields"


def main() -> None:
    """Fetch per-IPO context across open+closed+listed mainboard IPOs; write token-free cache."""
    parser = argparse.ArgumentParser(description="Refresh the per-IPO Upstox context cache.")
    parser.add_argument(
        "--data-dir",
        default="data_store",
        help="the app's data dir (dev default ./data_store; pass the installed app's per-user "
        "engine-data dir, or the VM's data plane)",
    )
    args = parser.parse_args()

    token = _load_token()
    ids = _list_ids(token)
    ipos: dict[str, dict[str, object]] = {}
    for sym, ipo_id in sorted(ids.items()):
        entry = _context(token, ipo_id)
        time.sleep(_DETAIL_PAUSE_S)
        if entry:
            ipos[sym] = entry

    out_dir = Path(args.data_dir) / "context"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "ipo_context.json"
    payload = {"refreshed_at": datetime.now(tz=UTC).astimezone().isoformat(), "ipos": ipos}
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    n_reg = sum(1 for e in ipos.values() if e.get("registrar"))
    n_rhp = sum(1 for e in ipos.values() if e.get("rhp_url"))
    n_lot = sum(1 for e in ipos.values() if e.get("lot_size"))
    # N of M — a gap between resolved ids and written entries flags failures/empties; the per-IPO
    # stderr lines above (``[context …] HTTP …``) distinguish a failed fetch from a genuine absence.
    print(f"\nWrote {len(ipos)} of {len(ids)} IPO context entries to {out_path} (token-free).")
    print(f"  with registrar: {n_reg}   with rhp_url: {n_rhp}   with lot_size: {n_lot}")
    for sym in list(ipos)[:8]:
        raw = ipos[sym].get("registrar")
        r = raw if isinstance(raw, dict) else {}
        reg = str(r.get("name") or r.get("short") or "-")[:28]
        has_rhp = "Y" if ipos[sym].get("rhp_url") else "-"
        print(f"  {sym:<12} registrar={reg:<28} rhp={has_rhp}")


if __name__ == "__main__":
    main()
