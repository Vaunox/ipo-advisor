"""NiftyRegime: cold/hot classification from an index series."""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

from ipo.calibration.regime import NiftyRegime


def _write_nifty(path: Path, closes: list[float]) -> None:
    start = date(2020, 1, 1)
    with path.open("w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle)
        w.writerow(["date", "close"])
        for i, c in enumerate(closes):
            w.writerow([(start + timedelta(days=i)).isoformat(), c])


def test_rising_tape_is_hot(tmp_path: Path) -> None:
    path = tmp_path / "nifty.csv"
    _write_nifty(path, [100.0 + i for i in range(130)])  # steadily rising
    regime = NiftyRegime(path)
    info = regime.regime_at(date(2020, 1, 1) + timedelta(days=120))
    assert info.trend_3m is not None and info.trend_3m > 0
    assert info.is_cold is False


def test_falling_tape_is_cold(tmp_path: Path) -> None:
    path = tmp_path / "nifty.csv"
    # Rise for 65 days, then fall hard for 65 — a correction.
    closes = [100.0 + i for i in range(65)] + [165.0 - 1.5 * i for i in range(65)]
    _write_nifty(path, closes)
    regime = NiftyRegime(path)
    info = regime.regime_at(date(2020, 1, 1) + timedelta(days=128))
    assert info.trend_3m is not None and info.trend_3m < 0  # negative 3-month trend
    assert info.drawdown is not None and info.drawdown < 0  # off the 3-month high
    assert info.is_cold is True


def test_insufficient_history_is_not_cold(tmp_path: Path) -> None:
    path = tmp_path / "nifty.csv"
    _write_nifty(path, [100.0 + i for i in range(30)])  # < 63 days
    regime = NiftyRegime(path)
    info = regime.regime_at(date(2020, 1, 1) + timedelta(days=20))
    assert info.trend_3m is None
    assert info.is_cold is False


def test_market_regime_feature_sign_and_bounds(tmp_path: Path) -> None:
    rising = tmp_path / "up.csv"
    _write_nifty(rising, [100.0 + i for i in range(130)])
    up = NiftyRegime(rising).market_regime_feature(date(2020, 1, 1) + timedelta(days=120))
    assert up is not None and 0.0 < up <= 1.0  # positive trend -> positive regime

    falling = tmp_path / "down.csv"
    _write_nifty(falling, [100.0 + i for i in range(65)] + [165.0 - 1.5 * i for i in range(65)])
    down = NiftyRegime(falling).market_regime_feature(date(2020, 1, 1) + timedelta(days=128))
    assert down is not None and -1.0 <= down < 0.0  # negative trend -> negative regime

    short = tmp_path / "short.csv"
    _write_nifty(short, [100.0 + i for i in range(30)])
    assert NiftyRegime(short).market_regime_feature(date(2020, 1, 1) + timedelta(days=20)) is None
