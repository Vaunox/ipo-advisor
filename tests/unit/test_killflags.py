"""Kill-flags: each veto condition triggers; a clean issue trips none."""

from __future__ import annotations

from datetime import date, datetime

from ipo.core.config import KillFlagConfig
from ipo.core.constants import IST
from ipo.core.types import IPOFeatures, IPORecord, Segment
from ipo.model.killflags import (
    COLLAPSING_GMP,
    NEAR_TOTAL_OFS,
    PROMOTER_LITIGATION,
    SME_SEGMENT,
    kill_flags,
)

_CFG = KillFlagConfig()


def _record(**over: object) -> IPORecord:
    base: dict[str, object] = dict(
        ipo_id="acme",
        name="Acme Ltd",
        segment=Segment.MAINBOARD,
        price_band_low=90.0,
        price_band_high=100.0,
        lot_size=10,
        issue_size_cr=500.0,
        open_date=date(2024, 1, 1),
        close_date=date(2024, 1, 3),
        promoter_litigation=False,
        captured_at=datetime(2024, 1, 3, 18, tzinfo=IST),
    )
    base.update(over)
    return IPORecord(**base)  # type: ignore[arg-type]


def _feats(**over: object) -> IPOFeatures:
    base: dict[str, object] = dict(
        ipo_id="acme",
        asof=datetime(2024, 1, 3, 18, tzinfo=IST),
        gmp_level=20.0,
        gmp_slope=2.0,
        qib_sub=50.0,
        ofs_fraction=0.3,
        book_closed=True,
    )
    base.update(over)
    return IPOFeatures(**base)  # type: ignore[arg-type]


def test_clean_issue_has_no_kill_flags() -> None:
    assert kill_flags(_record(), _feats(), _CFG) == []


def test_sme_segment_flagged() -> None:
    assert SME_SEGMENT in kill_flags(_record(segment=Segment.SME), _feats(), _CFG)


def test_collapsing_gmp_flagged() -> None:
    assert COLLAPSING_GMP in kill_flags(_record(), _feats(gmp_slope=-15.0), _CFG)


def test_borderline_gmp_slope_not_flagged() -> None:
    assert COLLAPSING_GMP not in kill_flags(_record(), _feats(gmp_slope=-9.0), _CFG)


def test_near_total_ofs_flagged() -> None:
    assert NEAR_TOTAL_OFS in kill_flags(_record(), _feats(ofs_fraction=0.98), _CFG)


def test_promoter_litigation_flagged() -> None:
    assert PROMOTER_LITIGATION in kill_flags(_record(promoter_litigation=True), _feats(), _CFG)
