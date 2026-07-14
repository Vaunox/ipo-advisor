"""V3-5 (RHP/DRHP links) DATA-SHAPE probe — is ``drhp_url`` populated on pre-close IPOs?

RESEARCH / OFF-MAIN. **You run this, not the assistant** (it authenticates with your Upstox
Analytics Token from ``UPSTOX_TOKEN`` / ``research/.env``; the token is never printed or written).
Output is token-free public IPO data — safe to share.

Context: the V3-6 probe found ``rhp_url`` 22/22 but ``drhp_url`` 0/22 on CLOSED+LISTED IPOs —
expected, since by then the RHP has superseded the draft. V3-5's open question is whether
``drhp_url`` is populated EARLIER (upcoming/open), which decides V3-5's rule:
  * drhp_url populated pre-close  → "show whichever document exists" (DRHP before the RHP is filed,
    RHP once it is) — and the UI must LABEL which one, since a draft and a final prospectus differ.
  * drhp_url null everywhere       → DRHP is dropped; V3-5 is RHP-only.

We don't know Upstox's status string for pre-close stages (earlier pulls only used listed/closed),
so this tries several candidates and reports which return data, then samples details for rhp_url /
drhp_url coverage + a few sample URLs.

Run:
    .venv/Scripts/python.exe research/fetch_upstox_drhp_check.py
    # then let the assistant read research/upstox_drhp_check.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_upstox_ipos import (  # noqa: E402
    _ISSUE_TYPE,
    _RECORDS,
    _get,
    _load_token,
    _rows_from_payload,
)

_OUT = Path(__file__).resolve().parent / "upstox_drhp_check.json"

# Candidate status strings for the pre-close lifecycle. We don't yet know which Upstox uses, so try
# a spread and report which returned IPOs. (closed/listed are proven from earlier pulls; included as
# a control so the report shows drhp_url there too.)
_CANDIDATE_STATUSES = ("upcoming", "open", "active", "pre_apply", "pre_open", "closed", "listed")
_SAMPLE_PER_STATUS = 12
_DETAIL_PAUSE_S = 0.3
_DOC_KEYS = ("rhp_url", "drhp_url")


def _list_for_status(token: str, status: str) -> list[dict]:
    """One page of the mainboard list for ``status`` (enough to tell if it's valid + to sample)."""
    path = f"/v2/ipos?status={status}&issue_type={_ISSUE_TYPE}&page_number=1&records={_RECORDS}"
    resp = _get(path, token)
    if resp.status_code != 200:
        return []
    return _rows_from_payload(resp.json())


def _detail(token: str, ipo_id: object) -> dict | None:
    resp = _get(f"/v2/ipos/{ipo_id}", token)
    if resp.status_code != 200:
        return None
    data = resp.json().get("data")
    obj = data if isinstance(data, dict) else (data[0] if isinstance(data, list) and data else None)
    return obj if isinstance(obj, dict) else None


def main() -> None:
    """Probe drhp_url/rhp_url coverage across candidate pre-close statuses; write token-free."""
    token = _load_token()
    by_status: dict[str, dict] = {}
    samples: list[dict] = []

    for status in _CANDIDATE_STATUSES:
        rows = _list_for_status(token, status)
        by_status[status] = {"list_count": len(rows), "sampled": 0, "coverage": {}}
        if not rows:
            continue
        cov = {k: 0 for k in _DOC_KEYS}
        n = 0
        for r in rows[:_SAMPLE_PER_STATUS]:
            if r.get("id") is None:
                continue
            obj = _detail(token, r["id"])
            time.sleep(_DETAIL_PAUSE_S)
            if obj is None:
                continue
            n += 1
            for k in _DOC_KEYS:
                if obj.get(k) not in (None, ""):
                    cov[k] += 1
            samples.append({
                "status_queried": status,
                "symbol": str(r.get("symbol", "")).upper(),
                "detail_status": obj.get("status"),
                "rhp_url": obj.get("rhp_url"),
                "drhp_url": obj.get("drhp_url"),
            })
        by_status[status]["sampled"] = n
        by_status[status]["coverage"] = {k: f"{cov[k]}/{n}" for k in _DOC_KEYS}

    _OUT.write_text(
        json.dumps({"by_status": by_status, "samples": samples}, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nWrote {_OUT} (token-free — safe to share).\n")
    print(f"{'status queried':<16}{'list':>6}{'sampled':>9}   rhp_url / drhp_url coverage")
    print("-" * 66)
    for s, info in by_status.items():
        cov = info["coverage"]
        cov_str = f"rhp {cov.get('rhp_url', '—')}  drhp {cov.get('drhp_url', '—')}" if cov else "—"
        print(f"{s:<16}{info['list_count']:>6}{info['sampled']:>9}   {cov_str}")
    print("\nsample docs (first 10):")
    for r in samples[:10]:
        print(f"  {r['symbol']:<12} [{r['detail_status']}] "
              f"rhp={'Y' if r['rhp_url'] else '-'} drhp={'Y' if r['drhp_url'] else '-'}")


if __name__ == "__main__":
    main()
