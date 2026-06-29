"""Market-regime classification for the regime stress-test (Nifty trend / drawdown).

Defines 'cold' objectively from the Nifty index at the listing date: a negative
3-month trend or a drawdown off the 3-month high. This is an *analysis* axis for
slicing backtest results by market condition — it is not fed to the model (the
backfill's ``market_regime`` feature was absent), so segmenting by it introduces no
look-ahead into the model's out-of-sample probabilities.
"""

from __future__ import annotations

import bisect
import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ipo.features.normalize import clamp

_TRADING_DAYS_3M = 63  # ~3 months of trading days
# A ±8% 3-month Nifty move maps to the ±1 regime extreme. Chosen a priori as a
# typical quarterly index swing — NOT fit to listing outcomes (no tuning to the slice).
_REGIME_FEATURE_SCALE = 0.08


@dataclass(frozen=True)
class RegimeInfo:
    """The Nifty regime at a date: 3-month trend, drawdown, and the cold flag."""

    trend_3m: float | None  # 63-trading-day return (None if insufficient history)
    drawdown: float | None  # return vs the trailing 3-month high (<= 0)
    is_cold: bool


class NiftyRegime:
    """Classifies a date as cold/hot from a Nifty daily-close series.

    Cold ≡ a negative 3-month trend OR a drawdown worse than ``drawdown_floor`` off
    the trailing 3-month high — a weak/correcting tape.
    """

    def __init__(self, csv_path: Path, *, drawdown_floor: float = -0.05) -> None:
        """Load the Nifty (date, close) series and set the cold drawdown threshold."""
        self._dates: list[date] = []
        self._closes: list[float] = []
        with csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                self._dates.append(date.fromisoformat(row["date"]))
                self._closes.append(float(row["close"]))
        self._floor = drawdown_floor

    def regime_at(self, day: date) -> RegimeInfo:
        """Return the regime as of the last trading day at or before ``day``."""
        idx = bisect.bisect_right(self._dates, day) - 1
        if idx < _TRADING_DAYS_3M:
            return RegimeInfo(trend_3m=None, drawdown=None, is_cold=False)
        now = self._closes[idx]
        prior = self._closes[idx - _TRADING_DAYS_3M]
        window_high = max(self._closes[idx - _TRADING_DAYS_3M : idx + 1])
        trend = now / prior - 1.0
        drawdown = now / window_high - 1.0
        is_cold = trend < 0.0 or drawdown < self._floor
        return RegimeInfo(trend_3m=trend, drawdown=drawdown, is_cold=is_cold)

    def is_cold(self, day: date) -> bool:
        """Convenience: True if ``day`` falls in a cold regime."""
        return self.regime_at(day).is_cold

    def market_regime_feature(self, asof: date) -> float | None:
        """Return the point-in-time ``market_regime`` feature in [-1, 1] as of ``asof``.

        A deterministic transform of the trailing 3-month Nifty trend (no fitting), so
        it is leakage-free by construction: it uses only index data up to ``asof`` (the
        decision-time clock). ``None`` if there is insufficient history.
        """
        trend = self.regime_at(asof).trend_3m
        if trend is None:
            return None
        return clamp(trend / _REGIME_FEATURE_SCALE, -1.0, 1.0)
