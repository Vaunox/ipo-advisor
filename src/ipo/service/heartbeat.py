"""Data-source freshness heartbeat (A4 part 4 — operate-phase hardening).

The recorder-heartbeat model, applied to every persisted feed the app depends on: each
data source declares how fresh it should be, and this reports whether it still is. It
surfaces a silently-dead scraper, a stale market series, or a holiday calendar that has
run off its edge — before any of them quietly corrupts a verdict.

Some feeds are *expected* to be stale while their forward recorders are deferred (Part
I-A standing rule), so staleness is reported as a warning, not a failure — only a missing
required artifact is an error. This is a read-only operator ritual; it changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Status values, in worsening order for reporting.
OK = "OK"
UNKNOWN = "UNKNOWN"  # present, but freshness can't be dated
STALE = "STALE"  # older than its declared max age (a warning, often expected)
MISSING = "MISSING"  # a required artifact is absent (an error)


@dataclass(frozen=True)
class FeedHealth:
    """One feed's freshness: a status, a human detail, and the raw age it was judged on."""

    name: str
    status: str
    detail: str
    data_through: date | None = None
    age_days: int | None = None

    @property
    def ok(self) -> bool:
        """True unless the feed is stale or missing (UNKNOWN-but-present is not a failure)."""
        return self.status in (OK, UNKNOWN)


def assess_feed(
    name: str,
    *,
    present: bool,
    data_through: date | None,
    today: date,
    max_age_days: int,
    basis: str = "last data",
) -> FeedHealth:
    """Judge a dated feed against its freshness budget.

    Args:
        name: Feed label for the report.
        present: Whether the underlying artifact exists.
        data_through: The most recent date the feed carries data for (its intrinsic
            freshness), or ``None`` when the artifact can't be dated.
        today: The reference date.
        max_age_days: How many days old ``data_through`` may be before it is STALE.
        basis: How ``data_through`` was derived, for an honest detail line — e.g.
            ``"last data"`` for a series, ``"last built"`` for a file's mtime.

    Returns:
        The feed's health.
    """
    if not present:
        return FeedHealth(name, MISSING, "artifact not found")
    if data_through is None:
        return FeedHealth(name, UNKNOWN, "present; freshness not datable")
    age = (today - data_through).days
    within = f"{basis} {data_through.isoformat()} ({age}d old"
    if age > max_age_days:
        return FeedHealth(name, STALE, f"{within} > {max_age_days}d budget)", data_through, age)
    return FeedHealth(name, OK, f"{within})", data_through, age)


def calendar_health(*, latest_year: int, review_due: bool) -> FeedHealth:
    """Health of the NSE holiday calendar from the ``core.calendar`` staleness guard."""
    if review_due:
        return FeedHealth(
            "holiday calendar",
            STALE,
            f"covered only through {latest_year}; add the next year's NSE circular (published "
            "each December)",
            date(latest_year, 12, 31),
        )
    return FeedHealth(
        "holiday calendar", OK, f"covered through {latest_year}", date(latest_year, 12, 31)
    )


def any_missing(feeds: list[FeedHealth]) -> bool:
    """True if any required artifact is absent (the only heartbeat *error* condition)."""
    return any(f.status == MISSING for f in feeds)


def stale_feeds(feeds: list[FeedHealth]) -> list[FeedHealth]:
    """The feeds that are older than their freshness budget (warnings)."""
    return [f for f in feeds if f.status == STALE]
