"""GMP feature construction (placeholder data source until Phase 5).

GMP is the dominant *direction* signal but unofficial and noisy (Inviolable Rule 5):
it sets the sign, never the certainty. These functions are point-in-time by
construction — they read only quotes dated at or before the as-of clock, so the
final-day GMP that is unknown at an earlier decision time can never leak in.

The historical GMP *series* is reconstructed by the Phase-5 scraper; here we only
define how a series becomes the level and final-days slope. Until then callers pass
``None``/empty and the features are ``None`` (never a silent zero).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class GmpQuote:
    """One grey-market premium observation: rupee premium on a given date."""

    on: date
    premium: float  # grey-market premium in rupees over the issue price


def _quotes_asof(series: Sequence[GmpQuote], asof_date: date) -> list[GmpQuote]:
    """Return quotes dated at or before ``asof_date``, sorted ascending (point-in-time)."""
    return sorted((q for q in series if q.on <= asof_date), key=lambda q: q.on)


def gmp_level_pct(
    series: Sequence[GmpQuote], asof_date: date, price_band_high: float
) -> float | None:
    """Return the last GMP as a percent of the price-band top, as of ``asof_date``.

    ``None`` if there is no quote at/before the as-of date or the band top is invalid.
    """
    if price_band_high <= 0:
        return None
    quotes = _quotes_asof(series, asof_date)
    if not quotes:
        return None
    return quotes[-1].premium / price_band_high * 100.0


def gmp_slope_pct(
    series: Sequence[GmpQuote],
    asof_date: date,
    price_band_high: float,
    *,
    days: int = 2,
) -> float | None:
    """Return the change in GMP% over the final ``days`` before the as-of date.

    A positive slope (GMP rising into the close) is healthier than the same level
    falling (Deep Dive #2). ``None`` if fewer than two quotes are available.
    """
    if price_band_high <= 0:
        return None
    quotes = _quotes_asof(series, asof_date)
    if len(quotes) < 2:
        return None
    last = quotes[-1]
    ref_date = last.on - timedelta(days=days)
    earlier = [q for q in quotes if q.on <= ref_date]
    base = earlier[-1] if earlier else quotes[0]
    return (last.premium - base.premium) / price_band_high * 100.0
