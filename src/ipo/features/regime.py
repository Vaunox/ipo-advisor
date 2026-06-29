"""Market-regime feature — listing-window context (Deep Dive #2).

A −1..+1 composite at the expected listing date: a Nifty trend read blended with a
volatility read. Hot, low-vol tapes lift listings; stressed tapes compress them.
Both inputs are expected pre-normalized to ``[-1, 1]`` by the caller (the live data
adapter that reads the index series); this keeps the blend a pure, testable function
with no network dependency. Weights live in config.
"""

from __future__ import annotations

from ipo.features.normalize import clamp


def compute_regime(
    trend: float,
    vol_stress: float,
    *,
    trend_weight: float,
    vol_weight: float,
) -> float:
    """Blend a trend read and a volatility-stress read into a −1..+1 regime score.

    Args:
        trend: 20-day Nifty trend in ``[-1, 1]`` (+1 = strong uptrend).
        vol_stress: volatility read in ``[-1, 1]`` (+1 = very stressed; subtracts).
        trend_weight: weight on the trend component.
        vol_weight: weight on the (negated) volatility component.
    """
    raw = trend_weight * trend - vol_weight * vol_stress
    return clamp(raw, -1.0, 1.0)
