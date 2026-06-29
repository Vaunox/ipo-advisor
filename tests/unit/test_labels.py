"""Label builder: gross returns vs issue price; no label without listing data."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from ipo.core.constants import IST
from ipo.core.types import IPORecord, Segment
from ipo.data.labels.builder import build_label, build_labels


def _record(ipo_id: str, **overrides: object) -> IPORecord:
    kwargs: dict[str, object] = dict(
        ipo_id=ipo_id,
        name=f"{ipo_id} Ltd",
        segment=Segment.MAINBOARD,
        price_band_low=475.0,
        price_band_high=500.0,
        lot_size=30,
        issue_size_cr=3042.0,
        open_date=date(2023, 11, 22),
        close_date=date(2023, 11, 24),
        captured_at=datetime(2023, 11, 24, 18, tzinfo=IST),
    )
    kwargs.update(overrides)
    return IPORecord(**kwargs)  # type: ignore[arg-type]


def test_label_uses_band_top_as_issue_price() -> None:
    # Tata Technologies: issue Rs 500, listed at Rs 1200 open (+140%, verified).
    rec = _record(
        "tatatech",
        listing_date=date(2023, 11, 30),
        listing_open=1200.0,
        listing_close=1314.30,
    )
    label = build_label(rec)
    assert label is not None
    assert label.issue_price == 500.0
    assert label.listing_return_open == pytest.approx(1.40, abs=1e-6)
    assert label.listing_return_close == pytest.approx((1314.30 - 500) / 500, abs=1e-6)


def test_negative_listing_label() -> None:
    # LIC: issue Rs 949, opened Rs 867.20 (-8.62%, verified).
    rec = _record(
        "lic",
        price_band_low=902.0,
        price_band_high=949.0,
        open_date=date(2022, 5, 4),
        close_date=date(2022, 5, 9),
        listing_date=date(2022, 5, 17),
        listing_open=867.20,
        listing_close=872.45,
    )
    label = build_label(rec)
    assert label is not None
    assert label.listing_return_open == pytest.approx(-0.0862, abs=1e-3)


def test_no_listing_yields_no_label() -> None:
    rec = _record("deferred")  # no listing_open/close
    assert build_label(rec) is None


def test_build_labels_skips_unlisted() -> None:
    listed = _record("a", listing_open=600.0, listing_close=650.0)
    unlisted = _record("b")
    labels = build_labels([listed, unlisted])
    assert [label.ipo_id for label in labels] == ["a"]
