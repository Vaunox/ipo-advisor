"""Relative-valuation feature (Deep Dive #2).

The listing pop is a demand event, so only *relative* valuation matters (issue P/E
vs peer median), never DCF. The "no listed peers" case is real (first-mover issues):
when the RHP declares no comparable peer, the feature is neutral-with-a-flag, not a
silent score — the flag lets the reason string say "no listed peer to anchor
valuation".
"""

from __future__ import annotations


def relative_valuation(
    issue_pe: float | None, peer_median_pe: float | None
) -> tuple[float | None, bool]:
    """Return (issue_pe / peer_median_pe, peerless_flag).

    - ``issue_pe`` missing -> ``(None, False)`` (optional data simply absent).
    - ``peer_median_pe`` missing -> ``(None, True)`` (declared no listed peer: flag set).
    - otherwise the ratio; ``>1`` is pricey (a brake on the pop).
    """
    if issue_pe is None:
        return None, False
    if peer_median_pe is None:
        return None, True
    if peer_median_pe <= 0:
        return None, False
    return issue_pe / peer_median_pe, False
