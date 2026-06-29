"""Reason generator: cites values, banners uncalibrated, surfaces watch + kill-flags."""

from __future__ import annotations

from datetime import datetime

from ipo.core.constants import IST
from ipo.core.types import IPOFeatures
from ipo.model.reason import UNCALIBRATED_BANNER, generate_reason


def _feats(**over: object) -> IPOFeatures:
    base: dict[str, object] = dict(
        ipo_id="acme",
        asof=datetime(2023, 11, 24, 18, tzinfo=IST),
        gmp_level=40.0,
        qib_sub=203.0,
        ofs_fraction=0.5,
        relative_valuation=2.0,
        book_closed=True,
    )
    base.update(over)
    return IPOFeatures(**base)  # type: ignore[arg-type]


_CONTRIB = {"gmp_level": 0.27, "qib_sub": 0.20, "ofs_fraction": -0.03, "relative_valuation": -0.10}


def test_uncalibrated_banner_present_when_not_calibrated() -> None:
    reason, _ = generate_reason(_feats(), _CONTRIB, [], calibrated=False, probability=0.9)
    assert UNCALIBRATED_BANNER in reason
    assert "P=" not in reason  # no probability cited while uncalibrated


def test_calibrated_reason_cites_probability_and_values() -> None:
    reason, watch = generate_reason(_feats(), _CONTRIB, [], calibrated=True, probability=0.72)
    assert "P=72%" in reason
    assert "QIB 203×" in reason
    assert UNCALIBRATED_BANNER not in reason
    # negatives become watch-items
    assert any("OFS" in w or "valuation" in w for w in watch)


def test_kill_flag_override_in_reason() -> None:
    reason, _ = generate_reason(
        _feats(), _CONTRIB, ["collapsing_gmp"], calibrated=True, probability=0.72
    )
    assert "Kill-flag override" in reason
    assert "collapsing_gmp" in reason
    assert "P=72%" in reason


def test_no_listed_peer_flag_appended_to_watch() -> None:
    feats = _feats(relative_valuation=None, flags=("no_listed_peer",))
    _, watch = generate_reason(feats, _CONTRIB, [], calibrated=False, probability=None)
    assert any("no listed peer" in w for w in watch)
