"""Conformal uncertainty bands (v2 B8, Idea 1) — an honesty layer, never a new probability.

Answers "how much should I trust this probability?" with a narrow, symmetric band around the
calibrated point estimate — e.g. "78%, realistic range 70–86%" — that **widens when the IPO's
market conditions are unfamiliar** (a sparse/cold regime, where fewer similar IPOs pin down the
rate) and narrows when familiar. It is the epistemic uncertainty in the *rate estimate*, not a
prediction interval for the binary listing outcome (that object is necessarily wide and
asymmetric — see docs/B8_CONFORMAL.md for why the estimate band was chosen).

It is **distribution-free conformal**, with the nonconformity taken at the *rate* level: the score
is ``|r_local(x) − p̂| / σ(x)`` where ``r_local`` is the kernel-weighted local outcome rate (the
best local estimate of the true rate) and ``σ(x) = sqrt(p̂(1−p̂) / density(x))`` is the rate's
standard error given the local evidence — larger where the regime is sparse. The conformal
quantile ``q`` sets the overall width so the band **covers the true local rate at its claimed
rate** (the B8 gate); ``σ`` supplies the per-IPO adaptivity (narrow when confident/familiar).

**This never changes the probability.** The band is computed downstream from the already-gated
calibrator's ``p̂`` and the point-in-time ``market_regime`` — display context only, the
quantitative companion to the B9/B2 cold flag. The scorer and calibrator are untouched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

_MIN_VAR = 1e-6  # floor on p̂(1−p̂) so a 0/1 point estimate still has a defined σ


@dataclass(frozen=True)
class ConformalBands:
    """A fitted rate-level conformal predictor of an uncertainty band around ``p̂``.

    Holds the out-of-sample calibration points (predicted prob, realized label, market regime),
    the kernel bandwidths, the density floor, and the conformal quantile ``q``. ``band`` centres on
    ``p̂`` and never alters it.
    """

    probs: tuple[float, ...]
    labels: tuple[int, ...]
    regimes: tuple[float, ...]
    q: float
    coverage: float
    prob_bw: float
    regime_bw: float
    density_floor: float

    def _arrays(self) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
        return (
            np.asarray(self.probs, dtype=np.float64),
            np.asarray(self.labels, dtype=np.float64),
            np.asarray(self.regimes, dtype=np.float64),
        )

    def _weights(self, p_hat: float, regime: float) -> NDArray[np.float64]:
        """Gaussian kernel over calibration points in (predicted-prob, market-regime) space."""
        probs, _, regimes = self._arrays()
        dp = (probs - p_hat) / self.prob_bw
        dr = (regimes - regime) / self.regime_bw
        return np.exp(-0.5 * (dp * dp + dr * dr))

    def _density(self, p_hat: float, regime: float, *, exclude: int | None = None) -> float:
        """Local evidence — the kernel-weighted count of similar calibration IPOs (floored)."""
        w = self._weights(p_hat, regime)
        if exclude is not None:
            w[exclude] = 0.0
        return max(float(w.sum()), self.density_floor)

    def sigma(self, p_hat: float, regime: float, *, exclude: int | None = None) -> float:
        """Standard error of the rate estimate: ``sqrt(p̂(1−p̂) / local density)``.

        Small where the model is confident (``p̂`` near 0/1) or the regime is well-populated;
        large where evidence is thin (cold/unfamiliar markets) — which is what widens the band.
        """
        var = max(p_hat * (1.0 - p_hat), _MIN_VAR)
        return float(np.sqrt(var / self._density(p_hat, regime, exclude=exclude)))

    def local_rate(self, p_hat: float, regime: float, *, exclude: int | None = None) -> float:
        """Kernel-weighted local outcome rate — the best local estimate of the true rate at x."""
        w = self._weights(p_hat, regime)
        if exclude is not None:
            w[exclude] = 0.0
        _, labels, _ = self._arrays()
        total = w.sum()
        return float((w * labels).sum() / total) if total > 0 else p_hat

    def band(self, p_hat: float, regime: float | None) -> tuple[float, float]:
        """Return the ``[lo, hi]`` estimate-uncertainty band around ``p_hat`` (clipped to [0, 1]).

        Symmetric ``p̂ ± q·σ(x)``. With no regime (insufficient index history), falls back to the
        median calibration regime. The point probability ``p_hat`` is unchanged.
        """
        reg = regime if regime is not None else float(np.median(self._arrays()[2]))
        half = self.q * self.sigma(p_hat, reg)
        return (max(0.0, p_hat - half), min(1.0, p_hat + half))


def fit_conformal_bands(
    probs: list[float],
    labels: list[int],
    regimes: list[float],
    *,
    coverage: float = 0.8,
    prob_bw: float = 0.15,
    regime_bw: float = 0.5,
    density_floor: float = 1.0,
) -> ConformalBands:
    """Fit the conformal quantile ``q`` from out-of-sample ``(p̂, y, regime)`` points.

    Rate-level nonconformity ``|r_local_{-i}(x_i) − p̂_i| / σ_{-i}(x_i)`` (leave-one-out, so ``q``
    is not optimistic) at the finite-sample rank ``⌈(n+1)·coverage⌉ / n``. Distribution-free: ``q``
    is set from the empirical scores, not a parametric assumption.
    """
    n = len(probs)
    if n < 2:
        raise ValueError(f"need >= 2 calibration points, got {n}")
    fitted = ConformalBands(
        tuple(probs), tuple(labels), tuple(regimes), q=0.0, coverage=coverage,
        prob_bw=prob_bw, regime_bw=regime_bw, density_floor=density_floor,
    )  # fmt: skip
    scores = np.array(
        [
            abs(fitted.local_rate(probs[i], regimes[i], exclude=i) - probs[i])
            / fitted.sigma(probs[i], regimes[i], exclude=i)
            for i in range(n)
        ]
    )
    rank = min(int(np.ceil((n + 1) * coverage)), n)
    q = float(np.sort(scores)[rank - 1])
    return ConformalBands(
        tuple(probs), tuple(labels), tuple(regimes), q=q, coverage=coverage,
        prob_bw=prob_bw, regime_bw=regime_bw, density_floor=density_floor,
    )  # fmt: skip


@dataclass(frozen=True)
class CoverageReport:
    """Held-out **rate-coverage**: how often the band contains the true local rate, + mean width."""

    claimed: float
    realized: float
    mean_width: float
    n: int


def coverage_report(
    probs: list[float],
    labels: list[int],
    regimes: list[float],
    *,
    coverage: float,
    prob_bw: float = 0.15,
    regime_bw: float = 0.5,
) -> CoverageReport:
    """Honest held-out rate-coverage via repeated cal/test splits (the B8 gate).

    Fits ``q`` and ``σ`` on a calibration half; on the held-out half measures how often the band
    contains that point's local outcome rate (estimated from the *calibration* neighbours, so the
    check is out-of-sample). Averaged over splits for stability.
    """
    p, y, r = np.asarray(probs), np.asarray(labels, dtype=float), np.asarray(regimes)
    rng = np.random.default_rng(0)
    covered = width = tested = 0.0
    for _ in range(20):
        perm = rng.permutation(len(p))
        cut = len(p) // 2
        ci, ti = perm[:cut], perm[cut:]
        bands = fit_conformal_bands(
            list(p[ci]), list(y[ci].astype(int)), list(r[ci]),
            coverage=coverage, prob_bw=prob_bw, regime_bw=regime_bw,
        )  # fmt: skip
        for j in ti:
            lo, hi = bands.band(float(p[j]), float(r[j]))
            rate = bands.local_rate(float(p[j]), float(r[j]))  # true-rate proxy from cal neighbours
            covered += float(lo <= rate <= hi)
            width += hi - lo
            tested += 1
    return CoverageReport(coverage, covered / tested, width / tested, len(p))


def save_conformal(bands: ConformalBands, path: Path) -> None:
    """Persist the fitted bands (calibration points + q + kernel config) as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "probs": list(bands.probs),
                "labels": list(bands.labels),
                "regimes": list(bands.regimes),
                "q": bands.q,
                "coverage": bands.coverage,
                "prob_bw": bands.prob_bw,
                "regime_bw": bands.regime_bw,
                "density_floor": bands.density_floor,
            }
        ),
        encoding="utf-8",
    )


def load_conformal(path: Path) -> ConformalBands:
    """Load persisted conformal bands."""
    d = json.loads(path.read_text(encoding="utf-8"))
    return ConformalBands(
        tuple(d["probs"]), tuple(int(x) for x in d["labels"]), tuple(d["regimes"]),
        q=d["q"], coverage=d["coverage"], prob_bw=d["prob_bw"],
        regime_bw=d["regime_bw"], density_floor=d["density_floor"],
    )  # fmt: skip
