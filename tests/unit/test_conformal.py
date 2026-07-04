"""Conformal uncertainty bands (B8 Idea 1): coverage, adaptivity, and round-trip."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ipo.calibration.conformal import (
    coverage_report,
    fit_conformal_bands,
    load_conformal,
    save_conformal,
)


def _synthetic() -> tuple[list[float], list[int], list[float]]:
    """Warm points well-calibrated (small residuals); cold points a coin-flip (large residuals)."""
    rng = np.random.default_rng(0)
    probs: list[float] = []
    labels: list[int] = []
    regimes: list[float] = []
    for _ in range(180):  # warm: dense (common) + well-calibrated (label ~ Bernoulli(p))
        p = float(rng.uniform(0.5, 0.95))
        probs.append(p)
        labels.append(int(rng.random() < p))
        regimes.append(0.5)
    for _ in range(40):  # cold: sparse (rare) + unreliable (label ~ coin flip) -> unfamiliar
        p = float(rng.uniform(0.5, 0.95))
        probs.append(p)
        labels.append(int(rng.random() < 0.5))
        regimes.append(-0.9)
    return probs, labels, regimes


def test_band_centers_on_p_and_stays_in_unit_interval() -> None:
    probs, labels, regimes = _synthetic()
    bands = fit_conformal_bands(probs, labels, regimes, coverage=0.8)
    for p in (0.05, 0.5, 0.78, 0.99):
        lo, hi = bands.band(p, 0.0)
        assert 0.0 <= lo <= p <= hi <= 1.0


def test_cold_regime_band_is_wider_than_warm() -> None:
    probs, labels, regimes = _synthetic()
    bands = fit_conformal_bands(probs, labels, regimes, coverage=0.8)
    # At a confident prediction (p=0.9) the separation is clean: a calibrated warm point has a
    # small residual (~0.18) while the cold coin-flip stays ~0.5, so cold must be the wider band.
    warm_lo, warm_hi = bands.band(0.9, 0.5)
    cold_lo, cold_hi = bands.band(0.9, -0.9)
    assert (cold_hi - cold_lo) > (warm_hi - warm_lo)  # unfamiliar/cold -> wider


def test_confident_prediction_band_is_narrower_than_uncertain() -> None:
    probs, labels, regimes = _synthetic()
    bands = fit_conformal_bands(probs, labels, regimes, coverage=0.8)
    confident = bands.band(0.95, 0.5)  # near-certain, familiar
    uncertain = bands.band(0.6, 0.5)  # mid-range, familiar
    assert (confident[1] - confident[0]) < (uncertain[1] - uncertain[0])


def test_coverage_is_honest_at_claimed_rate() -> None:
    # The B8 gate: realized coverage must be ~ the claimed rate on held-out splits.
    probs, labels, regimes = _synthetic()
    rep = coverage_report(probs, labels, regimes, coverage=0.8)
    assert 0.72 <= rep.realized <= 0.92  # conformal marginal coverage ~ 80% (finite-sample slack)
    assert rep.claimed == 0.8


def test_band_never_changes_the_point_probability() -> None:
    probs, labels, regimes = _synthetic()
    bands = fit_conformal_bands(probs, labels, regimes, coverage=0.8)
    p = 0.78
    lo, hi = bands.band(p, -0.5)
    assert p == 0.78  # the band brackets p; it does not and cannot mutate it
    assert lo <= p <= hi


def test_save_load_round_trip(tmp_path: Path) -> None:
    probs, labels, regimes = _synthetic()
    bands = fit_conformal_bands(probs, labels, regimes, coverage=0.8)
    path = tmp_path / "conformal.json"
    save_conformal(bands, path)
    loaded = load_conformal(path)
    assert loaded.band(0.7, -0.9) == bands.band(0.7, -0.9)
    assert loaded.q == bands.q
