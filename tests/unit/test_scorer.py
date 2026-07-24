"""WeightedScorer: named contributions, correct signs, None dropped, score = sum."""

from __future__ import annotations

from datetime import datetime

from ipo.core.config import FeaturesConfig, ValuationFeatureConfig
from ipo.core.constants import IST
from ipo.core.types import IPOFeatures
from ipo.model.scorer import WeightedScorer

_WEIGHTS = {
    "gmp_level": 0.30,
    "gmp_slope": 0.10,
    "qib_sub": 0.20,
    "nii_sub": 0.10,
    "retail_sub": 0.05,
    "anchor_quality": 0.10,
    "relative_valuation": 0.10,
    "ofs_fraction": 0.05,
    "market_regime": 0.10,
}


def _scorer() -> WeightedScorer:
    return WeightedScorer(_WEIGHTS, FeaturesConfig())


def _feats(**over: object) -> IPOFeatures:
    base: dict[str, object] = dict(
        ipo_id="acme",
        asof=datetime(2023, 11, 24, 18, tzinfo=IST),
        gmp_level=40.0,
        gmp_slope=5.0,
        qib_sub=100.0,
        nii_sub=60.0,
        retail_sub=15.0,
        anchor_quality=0.8,
        relative_valuation=1.0,
        ofs_fraction=0.2,
        market_regime=0.5,
        book_closed=True,
    )
    base.update(over)
    return IPOFeatures(**base)  # type: ignore[arg-type]


def test_contributions_are_named_and_positive_for_good_signals() -> None:
    c = _scorer().contributions(_feats())
    for key in ("gmp_level", "qib_sub", "anchor_quality", "market_regime"):
        assert c[key] > 0


def test_valuation_is_a_brake_only() -> None:
    pricey = _scorer().contributions(_feats(relative_valuation=2.0))
    inline = _scorer().contributions(_feats(relative_valuation=1.0))
    assert pricey["relative_valuation"] < 0  # priced above peers -> negative
    assert inline["relative_valuation"] == 0  # in line -> neutral, never positive


def test_overpricing_cap_is_config_driven_and_moves_the_brake() -> None:
    """F-3 threading: the valuation-brake cap (was the constant `_VALUATION_OVERPRICING_CAP`) now
    comes from config.features.valuation. An issue priced 200% above peers is beyond the default 1.0
    cap, so a wider cap admits more over-pricing -> a bigger brake. Driven THROUGH the config, so a
    mis-wire that ignored config (hardcoded the cap) fails this. `relative_valuation` weight here is
    a non-zero 0.10, so the contribution is genuinely exercised (not the shipped weight-0)."""
    feats = _feats(relative_valuation=3.0)  # overpricing 2.0, past the default 1.0 cap
    default = WeightedScorer(_WEIGHTS, FeaturesConfig()).contributions(feats)["relative_valuation"]
    wider = WeightedScorer(
        _WEIGHTS, FeaturesConfig(valuation=ValuationFeatureConfig(overpricing_cap=2.0))
    ).contributions(feats)["relative_valuation"]
    assert default == -0.10 * 1.0  # -weight * clamp(2.0, 0, 1.0) — the shipped cap
    assert wider == -0.10 * 2.0  # -weight * clamp(2.0, 0, 2.0) — the non-default cap MOVED it
    assert abs(wider) > abs(default)


def test_ofs_contribution_is_negative() -> None:
    assert _scorer().contributions(_feats(ofs_fraction=0.6))["ofs_fraction"] < 0


def test_negative_gmp_slope_contributes_negatively() -> None:
    assert _scorer().contributions(_feats(gmp_slope=-12.0))["gmp_slope"] < 0


def test_none_features_are_dropped() -> None:
    c = _scorer().contributions(
        _feats(anchor_quality=None, market_regime=None, relative_valuation=None)
    )
    assert "anchor_quality" not in c
    assert "market_regime" not in c
    assert "relative_valuation" not in c


def test_score_is_sum_of_contributions() -> None:
    feats = _feats()
    scorer = _scorer()
    assert scorer.score(feats) == sum(scorer.contributions(feats).values())
