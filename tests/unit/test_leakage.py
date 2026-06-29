"""GATE 2 — the point-in-time leakage suite (Deep Dive #4 §B).

The most important test in the system: it must PASS for the real, point-in-time
feature builder and FAIL for a deliberately-leaky one that peeks at post-listing
data. It also checks the as-of clock (future GMP quotes are ignored).
"""

from __future__ import annotations

from datetime import date, datetime

from ipo.core.constants import IST
from ipo.core.types import IPOFeatures, IPORecord, Segment
from ipo.features.build import build_features
from ipo.features.gmp import GmpQuote
from ipo.features.leakage import is_point_in_time_safe


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


_ASOF = datetime(2023, 11, 24, 18, tzinfo=IST)


def _leaky_build(record: IPORecord, asof: datetime) -> IPOFeatures:
    """A deliberately-leaky builder: it peeks at the listing price (the label)."""
    feats = build_features(record, asof)
    return feats.model_copy(update={"gmp_level": record.listing_open})


def test_real_features_are_point_in_time_safe() -> None:
    assert is_point_in_time_safe(build_features, _record(), _ASOF) is True


def test_real_features_pit_safe_with_gmp_series() -> None:
    series = [GmpQuote(date(2023, 11, 23), 120.0), GmpQuote(date(2023, 11, 24), 150.0)]
    builder = lambda r, a: build_features(r, a, gmp_series=series)  # noqa: E731
    assert is_point_in_time_safe(builder, _record(), _ASOF) is True


def test_leaky_feature_is_detected() -> None:
    # The suite MUST fail on a feature that reads post-listing data.
    assert is_point_in_time_safe(_leaky_build, _record(), _ASOF) is False


def test_label_does_not_change_features() -> None:
    # Two records identical except for the listing outcome (the label) -> same features.
    win = _record(listing_open=1200.0, listing_close=1314.30)
    flop = _record(listing_open=410.0, listing_close=395.0)
    assert build_features(win, _ASOF).model_dump() == build_features(flop, _ASOF).model_dump()


def test_asof_clock_ignores_future_gmp_quotes() -> None:
    base = [GmpQuote(date(2023, 11, 24), 150.0)]
    with_future = base + [GmpQuote(date(2023, 11, 29), 999.0)]  # after asof
    a = build_features(_record(), _ASOF, gmp_series=base)
    b = build_features(_record(), _ASOF, gmp_series=with_future)
    assert a.gmp_level == b.gmp_level == 30.0
