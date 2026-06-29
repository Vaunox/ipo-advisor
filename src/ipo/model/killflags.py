"""Kill-flags — hard overrides that force SKIP (Layer 3, Deep Dive #3).

These veto an issue regardless of how good the score looks, because they signal a
*different kind* of risk than the weighted score measures. Kept separate from the
sum on purpose: a structurally bad issue must not be rescued by a strong GMP.
Thresholds are config sanity bounds, never tuned to maximize backtest return.

They read record-level context (segment, promoter litigation) that is not part of
the feature vector, plus the point-in-time GMP slope and OFS from the features.
"""

from __future__ import annotations

from ipo.core.config import KillFlagConfig
from ipo.core.types import IPOFeatures, IPORecord, Segment

# Stable kill-flag identifiers (also used in the reason string).
SME_SEGMENT = "sme_segment"
COLLAPSING_GMP = "collapsing_gmp"
NEAR_TOTAL_OFS = "near_total_ofs"
PROMOTER_LITIGATION = "promoter_litigation"


def kill_flags(record: IPORecord, features: IPOFeatures, config: KillFlagConfig) -> list[str]:
    """Return the list of triggered kill-flags (empty if none).

    Any non-empty result forces a ``SKIP`` verdict downstream.
    """
    flags: list[str] = []

    if record.segment is Segment.SME:
        flags.append(SME_SEGMENT)

    # Demand evaporating at the worst moment: a high level two days ago doesn't save it.
    if features.gmp_slope is not None and features.gmp_slope <= config.gmp_collapse_slope_pct:
        flags.append(COLLAPSING_GMP)

    # Near-total OFS: no fresh capital, pure promoter exit.
    if features.ofs_fraction is not None and features.ofs_fraction >= config.near_total_ofs:
        flags.append(NEAR_TOTAL_OFS)

    # Tail risk the listing-day model cannot price.
    if record.promoter_litigation:
        flags.append(PROMOTER_LITIGATION)

    return flags
