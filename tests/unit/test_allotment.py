"""Retail allotment-odds proxy (v2 A3): formula properties + a real-data back-check.

The back-check measures how closely ``min(1, 1/retail_sub)`` tracks *actual* historical retail
allotment ratios — and it deliberately does NOT assert a tight match, because the proxy is a known
approximation (a whole-lot lottery decided by applicant count, not pro-rata of subscription). The
honest finding — the proxy systematically *under*-estimates by the average-lots-per-application
factor — is reported in docs/v2/A3_ALLOTMENT_ODDS.md; here we only guard the formula and the
direction/magnitude of the gap, never tune to the fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipo.service.allotment import retail_allotment_odds

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "retail_allotment_ratios.json"


# --- formula properties -------------------------------------------------------


def test_undersubscribed_retail_gets_full_allotment() -> None:
    assert retail_allotment_odds(0.5) == 1.0
    assert retail_allotment_odds(1.0) == 1.0


def test_oversubscribed_is_reciprocal() -> None:
    assert retail_allotment_odds(2.0) == pytest.approx(0.5)
    assert retail_allotment_odds(10.0) == pytest.approx(0.1)
    assert retail_allotment_odds(16.5) == pytest.approx(0.0606, abs=1e-3)


def test_missing_or_nonpositive_is_none() -> None:
    assert retail_allotment_odds(None) is None
    assert retail_allotment_odds(0.0) is None
    assert retail_allotment_odds(-1.0) is None


def test_monotonic_non_increasing_in_subscription() -> None:
    xs = [0.5, 1.0, 2.0, 5.0, 20.0, 100.0]
    odds = [retail_allotment_odds(x) for x in xs]
    assert all(
        a is not None and b is not None and a >= b for a, b in zip(odds, odds[1:], strict=False)
    )
    assert all(o is not None and 0.0 < o <= 1.0 for o in odds)


# --- real-data back-check (reports the gap; does NOT tune to it) ---------------


def _fixture_rows() -> list[dict[str, object]]:
    return list(json.loads(_FIX.read_text(encoding="utf-8"))["rows"])


def test_backcheck_proxy_underestimates_actual_within_a_loose_band() -> None:
    """On real oversubscribed IPOs the proxy is a *conservative* estimate: it under-states actual
    retail allotment odds (actual >= proxy) but stays the right order of magnitude (within ~3x).

    This is the honest relationship (actual ≈ k/retail_sub with k = avg lots/application >= 1), not
    a tolerance the formula was fitted to. If a future row violates it, that is a signal to look —
    not a reason to tune the formula.
    """
    for row in _fixture_rows():
        retail_sub = float(row["retail_sub"])  # type: ignore[arg-type]
        actual = float(row["actual_retail_allotment"])  # type: ignore[arg-type]
        proxy = retail_allotment_odds(retail_sub)
        assert proxy is not None
        # Proxy under-states (allow 10% slack for rounding in the reported ratio) ...
        assert proxy <= actual * 1.10, row["name"]
        # ... but is not off by more than ~3x (same ballpark, a usable estimate).
        assert actual <= proxy * 3.0, row["name"]


def test_backcheck_mean_underestimate_factor_is_reported() -> None:
    """Sanity: the mean actual/proxy factor (k) sits in the expected 1x-3x range for retail."""
    factors: list[float] = []
    for row in _fixture_rows():
        proxy = retail_allotment_odds(float(row["retail_sub"]))  # type: ignore[arg-type]
        assert proxy is not None
        factors.append(float(row["actual_retail_allotment"]) / proxy)  # type: ignore[arg-type]
    mean_k = sum(factors) / len(factors)
    assert 1.0 <= mean_k <= 3.0
