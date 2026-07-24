"""NiftyRegime: cold/hot classification from an index series."""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

from ipo.calibration.regime import NiftyRegime, merge_nifty_closes, update_nifty_csv


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


def test_trend_scale_moves_the_regime(tmp_path: Path) -> None:
    """F-1 threading: `trend_scale` (was the constant `_REGIME_FEATURE_SCALE`) now parameterises
    NiftyRegime. A non-default scale MOVES market_regime for the same trend (tighter scale = larger
    magnitude), so a mis-wire that fell back to a hardcoded scale fails this."""
    path = tmp_path / "nifty.csv"
    _write_nifty(path, [100.0 + 0.03 * i for i in range(130)])  # gentle rise → non-saturating
    day = date(2020, 1, 1) + timedelta(days=120)
    default = NiftyRegime(path).market_regime_feature(day)  # trend_scale 0.08
    tighter = NiftyRegime(path, trend_scale=0.04).market_regime_feature(day)  # half the scale
    assert default is not None and tighter is not None
    assert 0.0 < default < 1.0 and 0.0 < tighter < 1.0  # neither clamps — the difference is genuine
    assert tighter != default and abs(tighter) > abs(
        default
    )  # the non-default scale MOVED the output


def test_trend_days_moves_the_regime(tmp_path: Path) -> None:
    """F-1 threading: `trend_days` (was `_TRADING_DAYS_3M`) parameterises the trend window. A
    rose-then-fell tape trends UP over a long window but DOWN over a short one, so a non-default
    window flips the regime sign — a hardcoded-window fallback fails this."""
    path = tmp_path / "nifty.csv"
    _write_nifty(path, [100.0 + i for i in range(90)] + [190.0 - i for i in range(40)])
    day = date(2020, 1, 1) + timedelta(days=120)
    long_win = NiftyRegime(path).market_regime_feature(day)  # 63d → spans rise+fall, net up
    short_win = NiftyRegime(path, trend_days=20).market_regime_feature(day)  # last 20d → falling
    assert long_win is not None and short_win is not None
    assert long_win > 0.0 and short_win < 0.0  # opposite signs → the non-default window MOVED it


def test_drawdown_floor_moves_is_cold(tmp_path: Path) -> None:
    """F-1 threading: `drawdown_floor` parameterises the cold-drawdown rule (feeds `is_cold`, the
    OFFLINE stress-test read — no live consumer). A tape that pulled ~2.3% off its high while still
    trending UP is cold ONLY by the drawdown rule, so a non-default floor MOVES is_cold."""
    path = tmp_path / "nifty.csv"
    _write_nifty(
        path, [100.0 + i / 3 for i in range(91)] + [130.0 - (i + 1) * 0.1 for i in range(39)]
    )
    day = date(2020, 1, 1) + timedelta(days=120)
    info = NiftyRegime(path).regime_at(
        day
    )  # floor -0.05: drawdown -0.023 not past it, trend up → hot
    assert info.trend_3m is not None and info.trend_3m > 0.0 and info.is_cold is False
    shallow = NiftyRegime(path, drawdown_floor=-0.001).is_cold(day)  # -0.023 < -0.001 → cold
    assert shallow is True  # the non-default floor MOVED is_cold


def test_merge_nifty_closes_is_append_only() -> None:
    existing = [(date(2020, 1, 1), 100.0), (date(2020, 1, 2), 101.0)]
    new = [
        (date(2020, 1, 2), 999.0),  # conflicts with an existing date -> MUST be ignored
        (date(2020, 1, 3), 102.0),  # genuinely new -> added
    ]
    assert merge_nifty_closes(existing, new) == [
        (date(2020, 1, 1), 100.0),
        (date(2020, 1, 2), 101.0),  # preserved, NOT overwritten by 999.0
        (date(2020, 1, 3), 102.0),
    ]


def test_refresh_preserves_past_regime(tmp_path: Path) -> None:
    # The as-of clock: appending FUTURE closes must never change a PAST IPO's regime.
    path = tmp_path / "nifty.csv"
    _write_nifty(path, [100.0 + i for i in range(130)])
    past_day = date(2020, 1, 1) + timedelta(days=120)
    before = NiftyRegime(path).market_regime_feature(past_day)
    assert before is not None

    # Refresh with 30 future closes of an arbitrary (here: crashing) shape.
    future = [(date(2020, 1, 1) + timedelta(days=130 + i), 230.0 - 5.0 * i) for i in range(30)]
    assert update_nifty_csv(path, future) == 30  # all new dates added

    after = NiftyRegime(path).market_regime_feature(past_day)
    assert after == before  # byte-for-byte: a future close cannot bleed into a past regime
