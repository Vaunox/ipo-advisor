"""Anchor-quality feature — a 0..1 confidence composite (Deep Dive #2).

Three ingredients, combined with config weights (never hardcoded names in code):
1. fraction of the anchor book allotted to recognized marquee anchors;
2. value-weighted lock-in length (longer = more conviction);
3. whether the book was fully placed.

Missing anchor data -> ``None`` (not 0): absence of evidence is not a weak anchor.
"""

from __future__ import annotations

from collections.abc import Sequence

from ipo.core.types import AnchorAllotment
from ipo.features.normalize import clamp


def _is_recognized(investor: str, recognized: Sequence[str]) -> bool:
    name = investor.lower()
    return any(marquee.lower() in name for marquee in recognized)


def anchor_quality(
    anchor_book: Sequence[AnchorAllotment] | None,
    *,
    recognized: Sequence[str],
    weight_marquee: float,
    weight_lockin: float,
    weight_full_placement: float,
    lockin_reference_days: int,
    fully_placed: bool = True,
) -> float | None:
    """Return the 0..1 anchor-quality score, or ``None`` if there is no anchor data.

    ``fully_placed`` defaults to True (a disclosed anchor book is, in practice, placed);
    expose it so a partial placement can be reflected when that data is available.
    """
    if not anchor_book:
        return None
    total = sum(a.amount_cr for a in anchor_book)
    if total <= 0:
        return None

    marquee_frac = sum(a.amount_cr for a in anchor_book if _is_recognized(a.investor, recognized))
    marquee_frac /= total

    weighted_lockin = sum(a.lock_in_days * a.amount_cr for a in anchor_book) / total
    lockin_score = clamp(weighted_lockin / lockin_reference_days, 0.0, 1.0)

    placement_score = 1.0 if fully_placed else 0.0
    score = (
        weight_marquee * marquee_frac
        + weight_lockin * lockin_score
        + weight_full_placement * placement_score
    )
    return clamp(score, 0.0, 1.0)
