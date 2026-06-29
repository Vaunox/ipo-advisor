"""Normalization recipes: clamp, winsorize, saturate, signed_saturate."""

from __future__ import annotations

import pytest

from ipo.features.normalize import clamp, saturate, signed_saturate, winsorize


def test_clamp_bounds() -> None:
    assert clamp(5, 0, 10) == 5
    assert clamp(-1, 0, 10) == 0
    assert clamp(11, 0, 10) == 10
    with pytest.raises(ValueError):
        clamp(1, 10, 0)


def test_winsorize_caps_extremes() -> None:
    assert winsorize(250.0, 0.0, 200.0) == 200.0
    assert winsorize(50.0, 0.0, 200.0) == 50.0


def test_saturate_is_monotonic_and_bounded() -> None:
    assert saturate(-5, 20) == 0.0
    assert saturate(0, 20) == 0.0
    a, b = saturate(20, 20), saturate(80, 20)
    assert 0.0 < a < b < 1.0  # diminishing returns, never reaches 1
    with pytest.raises(ValueError):
        saturate(1, 0)


def test_signed_saturate_preserves_sign_and_bounds() -> None:
    assert signed_saturate(0, 15) == 0.0
    assert signed_saturate(30, 15) > 0
    assert signed_saturate(-30, 15) < 0
    # tanh saturates to exactly ±1.0 at large magnitudes (float) — bounds are inclusive.
    assert -1.0 <= signed_saturate(-1000, 15) < 0.0
    assert 0.0 < signed_saturate(1000, 15) <= 1.0
