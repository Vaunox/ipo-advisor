"""Point-in-time feature assembly — the Layer-2 output contract.

``build_features(record, asof, ...) -> IPOFeatures`` computes the model's input
vector using **only data known at or before ``asof``** (the decision time, i.e. the
end of the subscription-close day). This is the single rule the whole system's
honesty rests on (Inviolable Rule 2): the listing-day label is never read here, and
final-pre-listing values unknown at ``asof`` never leak in.

Identical in backtest and live: the backtest passes a historical ``asof``; live
passes "now". Missing features are explicit ``None``s (never silent zeros), so a
missing *critical* feature drives ``INSUFFICIENT_SIGNAL`` downstream.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from ipo.core.config import FeaturesConfig
from ipo.core.types import IPOFeatures, IPORecord
from ipo.features.anchor import anchor_quality
from ipo.features.gmp import GmpQuote, gmp_level_pct, gmp_slope_pct
from ipo.features.subscription import subscription_features
from ipo.features.valuation import relative_valuation


def build_features(
    record: IPORecord,
    asof: datetime,
    *,
    gmp_series: Sequence[GmpQuote] | None = None,
    market_regime: float | None = None,
    config: FeaturesConfig | None = None,
) -> IPOFeatures:
    """Build the point-in-time feature vector for ``record`` as of ``asof``.

    Args:
        record: the canonical IPO record.
        asof: the decision-time clock (timezone-aware IST). Nothing dated after this
            may inform a feature.
        gmp_series: point-in-time GMP observations (placeholder until Phase 5);
            quotes after ``asof`` are ignored by construction.
        market_regime: pre-computed −1..+1 regime at the expected listing date, or
            ``None`` (optional feature).
        config: feature-construction config; defaults are used if omitted.
    """
    cfg = config or FeaturesConfig()
    asof_date = asof.date()

    # The book is closed once the as-of clock reaches the close day's EOD.
    book_closed = asof_date >= record.close_date

    qib, nii, retail = subscription_features(record, book_closed=book_closed)

    series = gmp_series or []
    gmp_level = gmp_level_pct(series, asof_date, record.price_band_high)
    gmp_slope = gmp_slope_pct(series, asof_date, record.price_band_high, days=cfg.gmp.slope_days)

    rel_val, peerless = relative_valuation(record.issue_pe, record.peer_median_pe)

    anchor = anchor_quality(
        record.anchor_book,
        recognized=cfg.anchor.recognized,
        weight_marquee=cfg.anchor.weight_marquee,
        weight_lockin=cfg.anchor.weight_lockin,
        weight_full_placement=cfg.anchor.weight_full_placement,
        lockin_reference_days=cfg.anchor.lockin_reference_days,
    )

    flags: list[str] = []
    if not book_closed:
        flags.append("book_not_closed")
    if peerless:
        flags.append("no_listed_peer")
    if gmp_level is None:
        flags.append("gmp_unavailable")

    return IPOFeatures(
        ipo_id=record.ipo_id,
        asof=asof,
        gmp_level=gmp_level,
        gmp_slope=gmp_slope,
        qib_sub=qib,
        nii_sub=nii,
        retail_sub=retail,
        anchor_quality=anchor,
        relative_valuation=rel_val,
        ofs_fraction=record.ofs_fraction,
        market_regime=market_regime,
        book_closed=book_closed,
        flags=tuple(flags),
    )
