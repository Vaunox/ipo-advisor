"""NSE parsers tested against real captured fixtures (no network)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from ipo.core.constants import IST
from ipo.core.types import RawResponse
from ipo.data.sources.base import SourceError
from ipo.data.sources.nse import (
    _parse_band,
    _parse_money,
    _parse_nse_date,
    mainboard_since,
    parse_current_issues,
    parse_listing_prices,
    parse_past_issues,
    parse_subscription,
    parse_upcoming_issues,
)

_FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _raw(content: str) -> RawResponse:
    return RawResponse(
        source="nse",
        url="https://www.nseindia.com/api/x",
        fetched_at=datetime(2026, 1, 1, tzinfo=IST),
        content=content,
        content_hash="x",
    )


def test_parse_money_and_band() -> None:
    assert _parse_money("Rs.500") == 500.0
    assert _parse_money("Rs.1,250.50") == 1250.50
    assert _parse_money("-") is None
    assert _parse_band("Rs.475 to Rs.500", "") == (475.0, 500.0)
    assert _parse_band("", "Rs.136") == (136.0, 136.0)


def test_parse_nse_date_handles_mixed_case() -> None:
    assert _parse_nse_date("30-NOV-2023") == date(2023, 11, 30)
    assert _parse_nse_date("12-Apr-2013") == date(2013, 4, 12)
    assert _parse_nse_date("-") is None


def test_parse_past_issues_fixture() -> None:
    raw = _raw((_FIX / "nse_past_issues.json").read_text(encoding="utf-8"))
    issues = parse_past_issues(raw)
    assert len(issues) == 10
    segments = {i.segment for i in issues}
    assert segments == {"mainboard", "sme"}
    # Every row has a symbol and a parsed (or explicitly None) listing date.
    assert all(i.symbol for i in issues)


def test_parse_past_issues_fails_loud_on_drift() -> None:
    with pytest.raises(SourceError):
        parse_past_issues(_raw('{"not": "a list"}'))
    with pytest.raises(SourceError):
        parse_past_issues(_raw('[{"company": "X"}]'))  # missing symbol/securityType


def test_parse_subscription_fixture_matches_official() -> None:
    raw = _raw((_FIX / "nse_subscription_tatatech.json").read_text(encoding="utf-8"))
    sub = parse_subscription(raw)
    assert sub.qib == pytest.approx(203.41, abs=0.01)
    assert sub.nii == pytest.approx(62.11, abs=0.01)
    assert sub.retail == pytest.approx(16.50, abs=0.01)
    assert sub.total == pytest.approx(69.43, abs=0.01)


def test_parse_listing_prices_fixture() -> None:
    csv_text = (_FIX / "nse_bhavcopy_sample.csv").read_text(encoding="utf-8")
    assert parse_listing_prices(csv_text, "TATATECH") == (1200.0, 1313.0)
    assert parse_listing_prices(csv_text, "NOTLISTEDHERE") is None


def test_parse_listing_prices_unknown_columns_raise() -> None:
    with pytest.raises(SourceError):
        parse_listing_prices("a,b,c\n1,2,3\n", "TATATECH")


def test_mainboard_since_filters_segment_and_date() -> None:
    raw = _raw((_FIX / "nse_past_issues.json").read_text(encoding="utf-8"))
    issues = parse_past_issues(raw)
    filtered = mainboard_since(issues, date(2012, 1, 1))
    assert all(i.segment == "mainboard" for i in filtered)
    assert all(i.listing_date is not None for i in filtered)


def test_parse_current_issues_fixture() -> None:
    raw = _raw((_FIX / "nse_current_issue_sample.json").read_text(encoding="utf-8"))
    issues = parse_current_issues(raw)
    by_symbol = {i.symbol: i for i in issues}
    assert set(by_symbol) == {"KNACK", "ICELCO"}
    knack = by_symbol["KNACK"]
    assert knack.company == "Knack Packaging Limited"
    assert knack.segment == "mainboard"  # series EQ
    assert (knack.price_band_low, knack.price_band_high) == (161.0, 170.0)
    assert knack.open_date == date(2026, 7, 1)
    assert knack.close_date == date(2026, 7, 3)
    assert by_symbol["ICELCO"].segment == "sme"  # series SME


def test_parse_current_issues_bad_shape_raises() -> None:
    with pytest.raises(SourceError):
        parse_current_issues(_raw('{"not": "a list"}'))


def test_parse_upcoming_issues_fixture() -> None:
    raw = _raw((_FIX / "nse_upcoming_sample.json").read_text(encoding="utf-8"))
    issues = parse_upcoming_issues(raw)
    by_symbol = {i.symbol: i for i in issues}
    assert set(by_symbol) == {"FUTUREMB", "NOBANDSME"}  # empty-symbol row skipped, not fatal
    fut = by_symbol["FUTUREMB"]
    assert fut.segment == "mainboard"
    assert (fut.price_band_low, fut.price_band_high) == (100.0, 110.0)
    assert fut.open_date == date(2026, 7, 20)
    # a forthcoming row without a band parses but yields None -> skipped downstream (as designed)
    assert by_symbol["NOBANDSME"].price_band_high is None


def test_parse_upcoming_issues_handles_dict_wrapper() -> None:
    issues = parse_upcoming_issues(_raw('{"data": [{"symbol": "ABC", "series": "EQ"}]}'))
    assert [i.symbol for i in issues] == ["ABC"]


def test_parse_upcoming_issues_bad_shape_raises() -> None:
    with pytest.raises(SourceError):
        parse_upcoming_issues(_raw('"not a list"'))


def test_parse_subscription_captures_snii_bnii() -> None:
    raw = _raw((_FIX / "nse_active_category_sample.json").read_text(encoding="utf-8"))
    sub = parse_subscription(raw)
    assert sub.qib == pytest.approx(3.4772, abs=1e-3)
    assert sub.nii == pytest.approx(19.2186, abs=1e-3)
    assert sub.retail == pytest.approx(4.2335, abs=1e-3)
    assert sub.total == pytest.approx(7.2149, abs=1e-3)
    assert sub.nii_small == pytest.approx(17.1256, abs=1e-3)  # sNII (₹2–10L)
    assert sub.nii_big == pytest.approx(20.2651, abs=1e-3)  # bNII (>₹10L)
