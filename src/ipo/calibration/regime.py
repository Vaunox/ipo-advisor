"""Market-regime classification (Nifty trend / drawdown).

Defines 'cold' objectively from the Nifty index: a negative 3-month trend or a
drawdown off the 3-month high. Two consumers, kept strictly separate:

* **Analysis** (regime stress-test): slices backtest results by market condition.
* **Live cold-market FLAG** (Phase 6): ``market_regime_feature`` is fed into the live
  feature build, but its scorer weight is **0** — it drives the annotation only and
  must NOT move the calibrated probability (REGIME_FIX: "flag, don't force"). The
  calibrator's training set stays regime-free.

Point-in-time by construction: ``regime_at(day)`` reads only closes at/before ``day``
(``bisect`` ≤ day), so refreshing the series with future closes can never change a
past IPO's regime — ``merge_nifty_closes`` enforces this by being append-only.
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


class VixSeries:
    """India VIX daily series → a point-in-time volatility-stress read in [-1, 1] (v2 B2).

    Feeds the regime **cold-market flag only** (weight 0). ``vol_stress = clamp((vix - reference) /
    scale, -1, 1)`` — elevated VIX (fear) → +1 (stressed), calm VIX → -1. Point-in-time by
    construction (``bisect`` reads only closes at/before the decision day), so a later refresh of
    the series can never change a past IPO's stress read. ``reference`` / ``scale`` are a-priori
    (config), NOT fit to listing outcomes.
    """

    def __init__(self, csv_path: Path, *, reference: float = 15.0, scale: float = 15.0) -> None:
        """Load the India VIX (date, close) series and set the neutral reference + stress scale."""
        self._dates: list[date] = []
        self._closes: list[float] = []
        with csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                self._dates.append(date.fromisoformat(row["date"]))
                self._closes.append(float(row["close"]))
        self._reference = reference
        self._scale = scale

    def vol_stress_at(self, day: date) -> float | None:
        """VIX volatility-stress in [-1, 1] from the last close at/before ``day`` (None if none)."""
        idx = bisect.bisect_right(self._dates, day) - 1
        if idx < 0:
            return None
        return clamp((self._closes[idx] - self._reference) / self._scale, -1.0, 1.0)


def merge_nifty_closes(
    existing: list[tuple[date, float]], new: list[tuple[date, float]]
) -> list[tuple[date, float]]:
    """Append-only union of Nifty ``(date, close)`` rows, sorted ascending.

    Existing closes are **never** overwritten — only genuinely new dates are added.
    Combined with ``regime_at`` reading only closes at/before the decision day, this
    guarantees a later refresh cannot retroactively alter a past IPO's ``market_regime``:
    the as-of clock is preserved. This function is the safety gate; the caller fetches.
    """
    by_date: dict[date, float] = dict(existing)
    for day, close in new:
        by_date.setdefault(day, close)  # keep existing; add only new dates
    return sorted(by_date.items())


def update_nifty_csv(csv_path: Path, new_closes: list[tuple[date, float]]) -> int:
    """Append-only refresh of the Nifty CSV; returns the count of new dates added.

    Reads the existing ``date,close`` series, merges ``new_closes`` append-only (never
    mutating a stored close), and writes the union back sorted. Existing history — and thus
    every past IPO's regime — is invariant to the refresh.
    """
    existing: list[tuple[date, float]] = []
    if csv_path.is_file():
        with csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                try:
                    existing.append((date.fromisoformat(row["date"]), float(row["close"])))
                except (KeyError, ValueError):
                    continue
    existing_dates = {day for day, _ in existing}
    merged = merge_nifty_closes(existing, new_closes)
    added = sum(1 for day, _ in merged if day not in existing_dates)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "close"])
        for day, close in merged:
            writer.writerow([day.isoformat(), close])
    return added
