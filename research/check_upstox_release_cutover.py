"""Check 1 ADDENDUM — is Upstox's staleness pre-launch-only, or still present post-launch?

RESEARCH / OFF-MAIN, read-only, uses already-fetched local files only (no network).

Operator's hypothesis: Upstox's IPO API launched recently (per Upstox's own announcement,
effective **2026-05-23**); maybe only IPOs that closed *before* that date were backfilled once
and left stale, while IPOs closing *after* launch are captured by a live pipeline and are clean —
i.e. the errors aren't randomly jumbled, they cleanly separate at the launch date.

Tests this two ways against the same 1:1 matched pairs `compare_upstox_vs_nse.py` computes:
  1. Split matches strictly by the announced launch date (2026-05-23): pre-launch vs post-launch.
  2. Show the most-recent-N matches by close date in date order, so a "clean tail" (or lack of
     one) is visible directly, not just as a percentage.

Usage: PYTHONPATH=src python research/check_upstox_release_cutover.py
"""

from __future__ import annotations

from difflib import SequenceMatcher

from compare_upstox_vs_nse import _NAME_MATCH_MIN, Match, _load_ours, _load_upstox, _summary

_LAUNCH = "2026-05-23"


def _build_matches() -> list[Match]:
    ours = _load_ours()
    upstox, _ = _load_upstox()
    ours_by_date: dict[str, list[dict]] = {}
    for o in ours:
        ours_by_date.setdefault(o["date"], []).append(o)

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
            if o["total_sub"] <= 0:
                continue
            matched_upstox.add(ui)
            used_ours.add(id(o))
            matches.append(Match(d, o["name"], u["name"], o["total_sub"], u["total_sub"], sim))
    return matches


def main() -> None:
    """Split matches at the API's announced launch date and show the most-recent-N in order."""
    matches = _build_matches()
    matches_by_date = sorted(matches, key=lambda m: m.date)

    pre = [m for m in matches_by_date if m.date < _LAUNCH]
    post = [m for m in matches_by_date if m.date >= _LAUNCH]

    print(f"Launch-date split at {_LAUNCH} (Upstox's own announced IPO-API effective date)")
    print(f"pre-launch matches: {len(pre)}   post-launch matches: {len(post)}\n")
    _summary("PRE-launch (close < 2026-05-23)", pre)
    _summary("POST-launch (close >= 2026-05-23)", post)

    print("\n--- most recent 20 matches, in date order (does a clean tail appear?) ---")
    hdr = f"{'date':<11} {'ours':>8} {'upstox':>8} {'pct%':>7}  name"
    print(hdr)
    print("-" * 70)
    for m in matches_by_date[-20:]:
        flag = "" if abs(m.pct) <= 2 else "  <-- off"
        print(f"{m.date:<11} {m.ours:>8.2f} {m.upstox:>8.2f} {m.pct:>+7.1f}  "
              f"{m.name_ours[:32]}{flag}")


if __name__ == "__main__":
    main()
