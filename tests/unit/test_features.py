"""Feature construction: gmp, subscription, valuation, anchor, regime, build."""

from __future__ import annotations

from datetime import date, datetime

from ipo.core.config import FeaturesConfig
from ipo.core.constants import IST
from ipo.core.types import AnchorAllotment, IPORecord, Segment
from ipo.features.anchor import anchor_quality
from ipo.features.build import build_features
from ipo.features.gmp import GmpQuote, gmp_level_pct, gmp_slope_pct
from ipo.features.regime import compute_regime
from ipo.features.subscription import subscription_features
from ipo.features.valuation import relative_valuation


def _record(**overrides: object) -> IPORecord:
    kwargs: dict[str, object] = dict(
        ipo_id="acme",
        name="Acme Ltd",
        segment=Segment.MAINBOARD,
        price_band_low=475.0,
        price_band_high=500.0,
        lot_size=30,
        issue_size_cr=3042.0,
        ofs_fraction=0.4,
        open_date=date(2023, 11, 22),
        close_date=date(2023, 11, 24),
        listing_date=date(2023, 11, 30),
        qib_sub=203.0,
        nii_sub=62.0,
        retail_sub=16.0,
        issue_pe=32.5,
        peer_median_pe=40.0,
        listing_open=1200.0,
        listing_close=1314.30,
        captured_at=datetime(2023, 11, 24, 18, tzinfo=IST),
    )
    kwargs.update(overrides)
    return IPORecord(**kwargs)  # type: ignore[arg-type]


_CLOSE_EOD = datetime(2023, 11, 24, 18, tzinfo=IST)
_BEFORE_CLOSE = datetime(2023, 11, 23, 12, tzinfo=IST)


# --- GMP --------------------------------------------------------------------


def test_gmp_level_uses_last_quote_asof() -> None:
    series = [
        GmpQuote(date(2023, 11, 22), 100.0),
        GmpQuote(date(2023, 11, 24), 150.0),
        GmpQuote(date(2023, 11, 29), 400.0),  # after close: must be ignored
    ]
    level = gmp_level_pct(series, date(2023, 11, 24), 500.0)
    assert level == 30.0  # 150 / 500 * 100, the close-day quote (not the 400)


def test_gmp_level_none_when_empty_or_bad_band() -> None:
    assert gmp_level_pct([], date(2023, 11, 24), 500.0) is None
    assert gmp_level_pct([GmpQuote(date(2023, 11, 24), 150.0)], date(2023, 11, 24), 0.0) is None


def test_gmp_slope_sign() -> None:
    rising = [GmpQuote(date(2023, 11, 22), 50.0), GmpQuote(date(2023, 11, 24), 150.0)]
    falling = [GmpQuote(date(2023, 11, 22), 200.0), GmpQuote(date(2023, 11, 24), 150.0)]
    rise = gmp_slope_pct(rising, date(2023, 11, 24), 500.0, days=2)
    fall = gmp_slope_pct(falling, date(2023, 11, 24), 500.0, days=2)
    assert rise is not None and rise > 0
    assert fall is not None and fall < 0


def test_gmp_slope_none_with_single_quote() -> None:
    assert gmp_slope_pct([GmpQuote(date(2023, 11, 24), 150.0)], date(2023, 11, 24), 500.0) is None


# --- Subscription -----------------------------------------------------------


def test_subscription_gated_on_book_close() -> None:
    rec = _record()
    assert subscription_features(rec, book_closed=True) == (203.0, 62.0, 16.0)
    assert subscription_features(rec, book_closed=False) == (None, None, None)


# --- Valuation --------------------------------------------------------------


def test_relative_valuation_ratio() -> None:
    ratio, peerless = relative_valuation(40.0, 20.0)
    assert ratio == 2.0
    assert peerless is False


def test_relative_valuation_no_listed_peer_flagged() -> None:
    ratio, peerless = relative_valuation(40.0, None)
    assert ratio is None
    assert peerless is True


def test_relative_valuation_missing_issue_pe() -> None:
    ratio, peerless = relative_valuation(None, 20.0)
    assert ratio is None
    assert peerless is False


# --- Anchor -----------------------------------------------------------------


def test_anchor_quality_rewards_marquee_and_lockin() -> None:
    book = [
        AnchorAllotment(investor="SBI Mutual Fund", amount_cr=60.0, lock_in_days=90),
        AnchorAllotment(investor="Obscure Capital", amount_cr=40.0, lock_in_days=30),
    ]
    score = anchor_quality(
        book,
        recognized=["SBI", "ICICI Prudential"],
        weight_marquee=0.5,
        weight_lockin=0.3,
        weight_full_placement=0.2,
        lockin_reference_days=90,
    )
    assert score is not None
    assert 0.0 < score <= 1.0


def test_anchor_quality_none_when_no_book() -> None:
    assert (
        anchor_quality(
            None,
            recognized=["SBI"],
            weight_marquee=0.5,
            weight_lockin=0.3,
            weight_full_placement=0.2,
            lockin_reference_days=90,
        )
        is None
    )


# --- Regime -----------------------------------------------------------------


def test_compute_regime_blends_and_clamps() -> None:
    assert compute_regime(1.0, 0.0, trend_weight=0.6, vol_weight=0.4) == 0.6
    assert compute_regime(1.0, -1.0, trend_weight=0.6, vol_weight=0.4) == 1.0  # clamped
    assert compute_regime(-1.0, 1.0, trend_weight=0.6, vol_weight=0.4) == -1.0  # clamped


# --- build_features ---------------------------------------------------------


def test_build_features_at_close_uses_asof_data() -> None:
    rec = _record()
    feats = build_features(rec, _CLOSE_EOD)
    assert feats.book_closed is True
    assert feats.qib_sub == 203.0
    assert feats.ofs_fraction == 0.4
    assert feats.relative_valuation == 32.5 / 40.0
    # No GMP series supplied (placeholder): level is None and flagged, not zero.
    assert feats.gmp_level is None
    assert "gmp_unavailable" in feats.flags


def test_build_features_before_close_abstains_on_subscription() -> None:
    feats = build_features(_record(), _BEFORE_CLOSE)
    assert feats.book_closed is False
    assert feats.qib_sub is None
    assert "book_not_closed" in feats.flags


def test_build_features_with_gmp_and_regime() -> None:
    series = [GmpQuote(date(2023, 11, 24), 150.0)]
    feats = build_features(_record(), _CLOSE_EOD, gmp_series=series, market_regime=0.5)
    assert feats.gmp_level == 30.0
    assert feats.market_regime == 0.5


def test_build_features_flags_no_listed_peer() -> None:
    feats = build_features(_record(peer_median_pe=None), _CLOSE_EOD)
    assert feats.relative_valuation is None
    assert "no_listed_peer" in feats.flags


def test_build_features_uses_default_config_when_omitted() -> None:
    # Passing an explicit config behaves the same as relying on defaults here.
    rec = _record()
    assert build_features(rec, _CLOSE_EOD, config=FeaturesConfig()).qib_sub == 203.0
