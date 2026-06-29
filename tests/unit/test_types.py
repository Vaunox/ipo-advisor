"""Data-model validation: records fail loudly on bad data; the label never leaks."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from ipo.core.constants import IST
from ipo.core.types import (
    AnchorAllotment,
    IPOFeatures,
    IPORecord,
    Segment,
    Verdict,
    VerdictType,
)


def _base_record(**overrides: object) -> IPORecord:
    kwargs: dict[str, object] = dict(
        ipo_id="acme",
        name="Acme Ltd",
        segment=Segment.MAINBOARD,
        price_band_low=90.0,
        price_band_high=100.0,
        lot_size=150,
        issue_size_cr=500.0,
        open_date=date(2026, 1, 1),
        close_date=date(2026, 1, 3),
        captured_at=datetime(2026, 1, 3, 18, 0, tzinfo=IST),
    )
    kwargs.update(overrides)
    return IPORecord(**kwargs)  # type: ignore[arg-type]


def test_issue_price_is_band_top() -> None:
    rec = _base_record()
    assert rec.issue_price == 100.0


def test_band_inversion_rejected() -> None:
    with pytest.raises(ValidationError):
        _base_record(price_band_low=110.0, price_band_high=100.0)


def test_close_before_open_rejected() -> None:
    with pytest.raises(ValidationError):
        _base_record(open_date=date(2026, 1, 5), close_date=date(2026, 1, 3))


def test_listing_before_close_rejected() -> None:
    with pytest.raises(ValidationError):
        _base_record(listing_date=date(2026, 1, 2))


def test_ofs_fraction_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        _base_record(ofs_fraction=1.5)


def test_record_is_immutable() -> None:
    rec = _base_record()
    with pytest.raises(ValidationError):
        rec.name = "Mutated"  # type: ignore[misc]


def test_anchor_allotment_rejects_negative_amount() -> None:
    with pytest.raises(ValidationError):
        AnchorAllotment(investor="Fund A", amount_cr=-1.0, lock_in_days=30)


def test_features_market_regime_bounds() -> None:
    with pytest.raises(ValidationError):
        IPOFeatures(ipo_id="acme", asof=datetime(2026, 1, 3, tzinfo=IST), market_regime=2.0)


def test_features_defaults_are_none_and_book_closed_false() -> None:
    feats = IPOFeatures(ipo_id="acme", asof=datetime(2026, 1, 3, tzinfo=IST))
    assert feats.gmp_level is None
    assert feats.qib_sub is None
    assert feats.book_closed is False


def test_verdict_probability_bounds() -> None:
    with pytest.raises(ValidationError):
        Verdict(ipo_id="acme", verdict=VerdictType.APPLY, probability=1.5)


def test_insufficient_signal_allows_none_probability() -> None:
    v = Verdict(ipo_id="acme", verdict=VerdictType.INSUFFICIENT_SIGNAL)
    assert v.probability is None
    assert v.reason == ""
