"""Graded regime-flag tiers (v2 B9): normal/soft/cold boundaries + the caveat mapping."""

from __future__ import annotations

from ipo.core.config import VerdictThresholds
from ipo.model.verdict import _REGIME_CAVEAT, regime_tier

_TH = VerdictThresholds()  # defaults: soft = -0.15, cold = -0.3


def test_normal_tier_above_soft_and_when_unknown() -> None:
    assert regime_tier(0.5, _TH) == "normal"
    assert regime_tier(-0.14, _TH) == "normal"  # just above the soft boundary
    assert regime_tier(None, _TH) == "normal"  # no regime history → no caveat


def test_soft_tier_between_soft_and_cold() -> None:
    assert regime_tier(-0.15, _TH) == "soft"  # boundary belongs to soft (≤ soft, > cold)
    assert regime_tier(-0.2, _TH) == "soft"
    assert regime_tier(-0.29, _TH) == "soft"


def test_cold_tier_at_or_below_cold() -> None:
    assert regime_tier(-0.3, _TH) == "cold"  # boundary belongs to cold (≤ cold)
    assert regime_tier(-0.6, _TH) == "cold"


def test_caveat_map_covers_soft_and_cold_only() -> None:
    assert set(_REGIME_CAVEAT) == {"soft", "cold"}
    assert "cold market" in _REGIME_CAVEAT["cold"]  # the UI keys on this exact phrase
    assert "softening market" in _REGIME_CAVEAT["soft"]
    assert "normal" not in _REGIME_CAVEAT  # normal tier → no caveat appended
