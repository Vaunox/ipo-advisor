"""GATE 3 — the three demo cases, end to end through features -> verdict.

strong -> APPLY, fading-GMP -> SKIP (kill-flag), unclosed book ->
INSUFFICIENT_SIGNAL. Output must be correct and grounded; the calibrator is still
the placeholder and is clearly marked not-for-release (no probability is shown).
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from ipo.core.config import AppConfig, load_config
from ipo.core.constants import IST
from ipo.core.types import AnchorAllotment, IPORecord, Segment, Verdict, VerdictType
from ipo.features.build import build_features
from ipo.features.gmp import GmpQuote
from ipo.model.calibrator_placeholder import PlaceholderCalibrator
from ipo.model.scorer import WeightedScorer
from ipo.model.verdict import evaluate

_CLOSE = date(2023, 11, 24)
_ASOF_CLOSE = datetime(2023, 11, 24, 18, tzinfo=IST)
_ASOF_BEFORE = datetime(2023, 11, 23, 12, tzinfo=IST)


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config(env="dev", environ={})


def _strong_record() -> IPORecord:
    return IPORecord(
        ipo_id="strongco-2023",
        name="StrongCo Ltd",
        segment=Segment.MAINBOARD,
        price_band_low=475.0,
        price_band_high=500.0,
        lot_size=30,
        issue_size_cr=3042.0,
        ofs_fraction=0.2,
        open_date=date(2023, 11, 22),
        close_date=_CLOSE,
        qib_sub=200.0,
        nii_sub=80.0,
        retail_sub=15.0,
        issue_pe=30.0,
        peer_median_pe=40.0,
        anchor_book=[AnchorAllotment(investor="SBI Mutual Fund", amount_cr=100.0, lock_in_days=90)],
        promoter_litigation=False,
        captured_at=_ASOF_CLOSE,
    )


def _evaluate(record: IPORecord, asof: datetime, config: AppConfig, gmp: list[GmpQuote]) -> Verdict:
    feats = build_features(record, asof, gmp_series=gmp, market_regime=0.5, config=config.features)
    scorer = WeightedScorer(config.feature_weights, config.features)
    return evaluate(record, feats, scorer=scorer, calibrator=PlaceholderCalibrator(), config=config)


def test_strong_issue_applies(config: AppConfig) -> None:
    rising = [GmpQuote(date(2023, 11, 22), 150.0), GmpQuote(_CLOSE, 200.0)]  # +40% level, rising
    v = _evaluate(_strong_record(), _ASOF_CLOSE, config, rising)
    assert v.verdict is VerdictType.APPLY
    assert v.kill_flags == []
    # Calibrator is the placeholder: verdict shown, probability withheld + banner.
    assert v.probability is None
    assert "UNCALIBRATED" in v.reason
    assert "QIB" in v.reason  # grounded in real values


def test_fading_gmp_skips_via_kill_flag(config: AppConfig) -> None:
    falling = [
        GmpQuote(date(2023, 11, 22), 250.0),
        GmpQuote(_CLOSE, 150.0),
    ]  # slope -20% (collapse)
    v = _evaluate(_strong_record(), _ASOF_CLOSE, config, falling)
    assert v.verdict is VerdictType.SKIP
    assert "collapsing_gmp" in v.kill_flags
    assert "Kill-flag override" in v.reason


def test_unclosed_book_is_insufficient_signal(config: AppConfig) -> None:
    rising = [GmpQuote(date(2023, 11, 22), 150.0)]
    v = _evaluate(_strong_record(), _ASOF_BEFORE, config, rising)
    assert v.verdict is VerdictType.INSUFFICIENT_SIGNAL
    assert v.probability is None
    assert "INSUFFICIENT_SIGNAL" in v.reason


def test_placeholder_calibrator_is_not_release_ready() -> None:
    calib = PlaceholderCalibrator()
    assert calib.passes_reliability_gate is False
    assert "NOT FOR RELEASE" in calib.version
