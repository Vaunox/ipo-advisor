"""India VIX volatility-stress read (v2 B2): the [-1, 1] mapping + point-in-time behavior."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ipo.calibration.regime import VixSeries


def _vix(tmp_path: Path, rows: list[tuple[str, float]], **kw: float) -> VixSeries:
    path = tmp_path / "vix.csv"
    path.write_text(
        "date,close\n" + "\n".join(f"{d},{c}" for d, c in rows) + "\n", encoding="utf-8"
    )
    return VixSeries(path, **kw)


def test_reference_maps_to_zero_stress(tmp_path: Path) -> None:
    v = _vix(tmp_path, [("2021-01-01", 15.0)], reference=15.0, scale=15.0)
    assert v.vol_stress_at(date(2021, 1, 5)) == 0.0


def test_high_vix_is_positive_stress_clamped(tmp_path: Path) -> None:
    v = _vix(tmp_path, [("2021-01-01", 30.0), ("2021-02-01", 90.0)], reference=15.0, scale=15.0)
    assert v.vol_stress_at(date(2021, 1, 10)) == pytest.approx(1.0)  # (30-15)/15
    assert v.vol_stress_at(date(2021, 2, 10)) == 1.0  # clamped at +1


def test_low_vix_is_negative_stress_clamped(tmp_path: Path) -> None:
    v = _vix(tmp_path, [("2021-01-01", 22.5), ("2021-02-01", 10.0)], reference=30.0, scale=15.0)
    assert v.vol_stress_at(date(2021, 1, 10)) == pytest.approx(-0.5)  # (22.5-30)/15
    assert v.vol_stress_at(date(2021, 2, 10)) == -1.0  # (10-30)/15 = -1.33 → clamp -1


def test_point_in_time_reads_last_close_at_or_before_day(tmp_path: Path) -> None:
    v = _vix(tmp_path, [("2021-01-04", 30.0), ("2021-01-06", 45.0)], reference=15.0, scale=15.0)
    assert v.vol_stress_at(date(2020, 12, 31)) is None  # before the first close
    assert v.vol_stress_at(date(2021, 1, 4)) == pytest.approx(1.0)  # exact day
    # between closes → the last one at/before the day (never a future value)
    assert v.vol_stress_at(date(2021, 1, 5)) == pytest.approx(1.0)
    assert v.vol_stress_at(date(2021, 1, 6)) == 1.0  # (45-15)/15 → clamped
