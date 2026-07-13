"""Check 1 — compare Upstox `total_subscription` vs our NSE-sourced final total_sub.

RESEARCH / OFF-MAIN. Reads two local files only (no network, no token):
  * our backfill CSV (NSE-sourced final at-close overall multiple), and
  * research/upstox_pull.json (the token-free Upstox pull).

Joins on subscription-close date (our ``close_date`` == Upstox ``bidding_end_date``) plus a
fuzzy name match (both sources spell names differently — "… IPO" / "… Limited"), then reports,
per matched mainboard IPO, our value vs Upstox's, the delta, and the % difference — plus summary
stats (how many agree within 2% / 5% / 10%). Upstox rows with total_subscription 0.0 are dropped
(Upstox does not populate subscription before ~Nov 2024 / for REITs-InvITs), and are reported
separately so the coverage gap is explicit.

Usage: PYTHONPATH=src python research/compare_upstox_vs_nse.py
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_CSV = _REPO / "data" / "backfill" / "mainboard_ipos.csv"
_PULL = _REPO / "research" / "upstox_pull.json"
_NAME_MATCH_MIN = 0.55  # min normalized-name similarity to accept a same-date match

_SUFFIXES = re.compile(
    r"\b(ipo|limited|ltd|private|pvt|company|co|corporation|corp|industries|"
    r"technologies|solutions|india|the)\b",
    re.IGNORECASE,
)


def _norm(name: str) -> str:
    """Lowercase, drop corporate suffixes/punctuation → a comparable name core."""
    name = re.sub(r"\(.*?\)", " ", name)  # drop parentheticals e.g. (BCCL)
    name = _SUFFIXES.sub(" ", name)
    name = re.sub(r"[^a-z0-9]+", " ", name.lower())
    return re.sub(r"\s+", " ", name).strip()


@dataclass(frozen=True)
class Match:
    """One IPO present in both sources: our NSE final vs Upstox's total_subscription."""

    date: str
    name_ours: str
    name_upstox: str
    ours: float
    upstox: float
    name_sim: float

    @property
    def delta(self) -> float:
        """Upstox minus ours (negative = Upstox understates)."""
        return self.upstox - self.ours

    @property
    def pct(self) -> float:
        """Signed percentage difference of Upstox vs our value."""
        return 100.0 * self.delta / self.ours if self.ours else float("nan")


def _load_ours() -> list[dict]:
    rows = []
    with _CSV.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("segment", "mainboard") != "mainboard":
                continue
            if not r.get("total_sub") or not r.get("close_date"):
                continue
            rows.append(
                {
                    "name": r["name"],
                    "date": r["close_date"][:10],
                    "total_sub": float(r["total_sub"]),
                    "norm": _norm(r["name"]),
                }
            )
    return rows


def _load_upstox() -> tuple[list[dict], int]:
    data = json.loads(_PULL.read_text(encoding="utf-8"))
    live, zero = [], 0
    for r in data:
        ts = r.get("total_subscription")
        try:
            val = float(ts)
        except (TypeError, ValueError):
            continue
        if val <= 0.0:
            zero += 1
            continue
        live.append(
            {
                "name": r.get("name", ""),
                "date": str(r.get("bidding_end_date") or "")[:10],
                "total_sub": val,
                "norm": _norm(r.get("name", "")),
            }
        )
    return live, zero


def main() -> None:
    """Join the two sources on close date + name and print the agreement report."""
    ours = _load_ours()
    upstox, n_zero = _load_upstox()
    ours_by_date: dict[str, list[dict]] = {}
    for o in ours:
        ours_by_date.setdefault(o["date"], []).append(o)

    # Strict 1:1 matching per close date: rank all cross pairs on a date by name
    # similarity, then assign greedily so no IPO is matched twice (fixes same-date bleed).
    matches: list[Match] = []
    matched_upstox: set[int] = set()
    all_dates = {u["date"] for u in upstox} & set(ours_by_date)
    for d in all_dates:
        us_here = [(i, u) for i, u in enumerate(upstox) if u["date"] == d]
        pairs = []
        for ui, u in us_here:
            for o in ours_by_date[d]:
                pairs.append((SequenceMatcher(None, o["norm"], u["norm"]).ratio(), ui, u, o))
        pairs.sort(key=lambda p: p[0], reverse=True)
        used_ours: set[int] = set()
        for sim, ui, u, o in pairs:
            if sim < _NAME_MATCH_MIN or ui in matched_upstox or id(o) in used_ours:
                continue
            if o["total_sub"] <= 0:  # can't take a % against a zero baseline
                continue
            matched_upstox.add(ui)
            used_ours.add(id(o))
            matches.append(
                Match(d, o["name"], u["name"], o["total_sub"], u["total_sub"], sim)
            )
    unmatched = [u for i, u in enumerate(upstox) if i not in matched_upstox]

    matches.sort(key=lambda m: abs(m.pct), reverse=True)
    print(f"Our mainboard rows: {len(ours)} | Upstox live(>0): {len(upstox)} | "
          f"Upstox zero/unpopulated: {n_zero}")
    print(f"Matched 1:1 pairs (same close date + name): {len(matches)}")
    print(f"Upstox live rows unmatched (newer than our backfill / REIT / no date twin): "
          f"{len(unmatched)}\n")

    hdr = f"{'date':<11} {'ours':>8} {'upstox':>8} {'delta':>8} {'pct%':>7} {'sim':>5}  name"
    print(hdr)
    print("-" * 88)
    for m in matches:
        print(f"{m.date:<11} {m.ours:>8.2f} {m.upstox:>8.2f} {m.delta:>+8.2f} "
              f"{m.pct:>+7.1f} {m.name_sim:>5.2f}  {m.name_ours[:36]}")

    _summary("ALL matched", matches)
    cut = "2025-09-01"
    _summary(f"RECENT (close >= {cut})", [m for m in matches if m.date >= cut])
    _summary(f"OLDER  (close <  {cut})", [m for m in matches if m.date < cut])


def _summary(label: str, ms: list[Match]) -> None:
    """Print the |%-difference| distribution and the direction of the big gaps."""
    if not ms:
        print(f"\n--- {label}: (none) ---")
        return
    aps = sorted(abs(m.pct) for m in ms)
    n = len(aps)
    within = [sum(1 for a in aps if a <= t) for t in (1, 2, 5, 10)]
    big = [m for m in ms if abs(m.pct) > 10]
    big_low = sum(1 for m in big if m.delta < 0)  # Upstox understates
    print(f"\n--- {label}: |% difference| ---")
    print(f"N={n}  median={aps[n // 2]:.2f}%  mean={sum(aps) / n:.2f}%  max={aps[-1]:.2f}%")
    print(f"within 1%: {within[0]}/{n}   within 2%: {within[1]}/{n}   "
          f"within 5%: {within[2]}/{n}   within 10%: {within[3]}/{n}   "
          f">10%: {len(big)}/{n}")
    if big:
        print(f"   of the >10% gaps: {big_low}/{len(big)} are Upstox-LOWER "
              f"(stale pre-close snapshot fingerprint)")


if __name__ == "__main__":
    main()
