"""Verdict engine: abstention-first, kill-flag override, threshold mapping."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from ipo.core.config import AppConfig, load_config
from ipo.core.constants import IST
from ipo.core.types import IPOFeatures, IPORecord, Segment, VerdictType
from ipo.model.calibrator_placeholder import PlaceholderCalibrator
from ipo.model.scorer import WeightedScorer
from ipo.model.verdict import evaluate, map_probability, missing_critical


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config(env="dev", environ={})


def _scorer(config: AppConfig) -> WeightedScorer:
    return WeightedScorer(config.feature_weights, config.features)


def _record(**over: object) -> IPORecord:
    base: dict[str, object] = dict(
        ipo_id="acme",
        name="Acme Ltd",
        segment=Segment.MAINBOARD,
        price_band_low=475.0,
        price_band_high=500.0,
        lot_size=30,
        issue_size_cr=3042.0,
        open_date=date(2023, 11, 22),
        close_date=date(2023, 11, 24),
        promoter_litigation=False,
        captured_at=datetime(2023, 11, 24, 18, tzinfo=IST),
    )
    base.update(over)
    return IPORecord(**base)  # type: ignore[arg-type]


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


# --- map_probability / missing_critical ------------------------------------


def test_map_probability_buckets() -> None:
    assert map_probability(0.70, 0.65, 0.50) is VerdictType.APPLY
    assert map_probability(0.55, 0.65, 0.50) is VerdictType.MARGINAL
    assert map_probability(0.40, 0.65, 0.50) is VerdictType.SKIP


def test_missing_critical_detects_gmp_and_unclosed_book() -> None:
    assert missing_critical(_feats(gmp_level=None), ["gmp_level", "qib_sub"]) == ["gmp_level"]
    assert "book_closed" in missing_critical(_feats(book_closed=False), ["gmp_level", "qib_sub"])


# --- evaluate: abstention ---------------------------------------------------


def test_unclosed_book_abstains(config: AppConfig) -> None:
    feats = _feats(book_closed=False, qib_sub=None)
    v = evaluate(
        _record(), feats, scorer=_scorer(config), calibrator=PlaceholderCalibrator(), config=config
    )
    assert v.verdict is VerdictType.INSUFFICIENT_SIGNAL
    assert v.probability is None


def test_missing_gmp_abstains_when_gmp_is_critical() -> None:
    # GMP is critical only once integrated (Phase 5). With that config, missing GMP abstains.
    config = load_config(
        env="dev",
        environ={},
        overrides={"features": {"critical_features": ["gmp_level", "qib_sub"]}},
    )
    v = evaluate(
        _record(),
        _feats(gmp_level=None),
        scorer=_scorer(config),
        calibrator=PlaceholderCalibrator(),
        config=config,
    )
    assert v.verdict is VerdictType.INSUFFICIENT_SIGNAL


def test_official_model_does_not_abstain_on_missing_gmp(config: AppConfig) -> None:
    # Phase-4 default: GMP is NOT critical, so a closed book with QIB still scores.
    v = evaluate(
        _record(),
        _feats(gmp_level=None),
        scorer=_scorer(config),
        calibrator=PlaceholderCalibrator(),
        config=config,
    )
    assert v.verdict is not VerdictType.INSUFFICIENT_SIGNAL


# --- evaluate: kill-flag override ------------------------------------------


def test_kill_flag_forces_skip_despite_strong_score(config: AppConfig) -> None:
    feats = _feats(gmp_slope=-15.0)  # collapsing GMP
    v = evaluate(
        _record(), feats, scorer=_scorer(config), calibrator=PlaceholderCalibrator(), config=config
    )
    assert v.verdict is VerdictType.SKIP
    assert "collapsing_gmp" in v.kill_flags


# --- evaluate: probability gating ------------------------------------------


def test_probability_hidden_while_uncalibrated(config: AppConfig) -> None:
    v = evaluate(
        _record(),
        _feats(),
        scorer=_scorer(config),
        calibrator=PlaceholderCalibrator(),
        config=config,
    )
    # The placeholder calibrator fails the reliability gate, so no number is shown.
    assert v.probability is None
    assert "UNCALIBRATED" in v.reason


def test_cold_market_is_flagged(config: AppConfig) -> None:
    # Regime stress-test outcome: cold market -> flag, not a forced probability.
    v = evaluate(
        _record(),
        _feats(market_regime=-0.6),
        scorer=_scorer(config),
        calibrator=PlaceholderCalibrator(),
        config=config,
    )
    assert any("cold market" in w for w in v.watch)


def test_hot_market_not_flagged(config: AppConfig) -> None:
    v = evaluate(
        _record(),
        _feats(market_regime=0.5),
        scorer=_scorer(config),
        calibrator=PlaceholderCalibrator(),
        config=config,
    )
    assert not any("cold market" in w for w in v.watch)


def test_weak_issue_skips(config: AppConfig) -> None:
    # Weakness comes from the LIVE drivers — thin subscription and falling GMP. The OFS /
    # valuation / regime brakes are weight-0 (disproven by the enhancement gate, docs/
    # ENHANCEMENT_GATE.md), so they can no longer manufacture a SKIP; this keeps the test honest
    # about what actually moves the score.
    weak = _feats(
        gmp_level=1.0,
        gmp_slope=-3.0,
        qib_sub=0.3,
        nii_sub=0.2,
        retail_sub=0.3,
    )
    v = evaluate(
        _record(), weak, scorer=_scorer(config), calibrator=PlaceholderCalibrator(), config=config
    )
    assert v.verdict is VerdictType.SKIP
    assert not v.kill_flags  # SKIP from the score, not an override
