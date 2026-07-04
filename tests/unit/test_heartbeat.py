"""Data-source freshness heartbeat: per-feed assessment, calendar, and roll-ups."""

from __future__ import annotations

from datetime import date

from ipo.service.heartbeat import (
    MISSING,
    OK,
    STALE,
    UNKNOWN,
    any_missing,
    assess_feed,
    calendar_health,
    stale_feeds,
)

_TODAY = date(2026, 7, 4)


def test_fresh_feed_is_ok() -> None:
    h = assess_feed(
        "vix", present=True, data_through=date(2026, 7, 3), today=_TODAY, max_age_days=7
    )
    assert h.status == OK
    assert h.ok
    assert h.age_days == 1


def test_old_feed_is_stale() -> None:
    h = assess_feed(
        "vix", present=True, data_through=date(2026, 5, 1), today=_TODAY, max_age_days=7
    )
    assert h.status == STALE
    assert not h.ok
    assert h.age_days == 64


def test_missing_artifact_is_missing() -> None:
    h = assess_feed("models", present=False, data_through=None, today=_TODAY, max_age_days=120)
    assert h.status == MISSING
    assert not h.ok


def test_present_but_undatable_is_unknown_not_failure() -> None:
    h = assess_feed("blob", present=True, data_through=None, today=_TODAY, max_age_days=30)
    assert h.status == UNKNOWN
    assert h.ok  # present but undatable is not a failure


def test_boundary_age_equals_budget_is_ok() -> None:
    h = assess_feed("x", present=True, data_through=date(2026, 6, 27), today=_TODAY, max_age_days=7)
    assert h.age_days == 7
    assert h.status == OK  # exactly at budget is not yet stale


def test_calendar_health_ok_and_stale() -> None:
    assert calendar_health(latest_year=2027, review_due=False).status == OK
    stale = calendar_health(latest_year=2026, review_due=True)
    assert stale.status == STALE
    assert "2026" in stale.detail


def test_rollups() -> None:
    feeds = [
        assess_feed("a", present=True, data_through=_TODAY, today=_TODAY, max_age_days=7),
        assess_feed("b", present=True, data_through=date(2026, 1, 1), today=_TODAY, max_age_days=7),
        assess_feed("c", present=False, data_through=None, today=_TODAY, max_age_days=7),
    ]
    assert any_missing(feeds)
    assert [f.name for f in stale_feeds(feeds)] == ["b"]
