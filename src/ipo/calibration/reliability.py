"""Reliability metrics — does a stated probability mean what it says (Deep Dive #4).

Calibration (not just discrimination) is the deliverable: when the model says 70%,
the event should happen ~70% of the time. This module provides the library-agnostic
reliability binning from Deep Dive #4 plus ECE, Brier, AUC, and the base rate — the
raw numbers the reliability gate and the calibration report are built from.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class ReliabilityBin:
    """One reliability-diagram bucket: mean predicted vs observed rate and count."""

    mean_predicted: float
    observed_rate: float
    count: int


@dataclass(frozen=True)
class ReliabilityReport:
    """Per-bin reliability plus the scalar calibration/discrimination metrics."""

    bins: list[ReliabilityBin]
    ece: float
    brier: float
    auc: float
    base_rate: float
    n: int


def _as_arrays(
    probs: list[float], labels: list[int]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    p = np.asarray(probs, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64)
    if p.shape != y.shape:
        raise ValueError("probs and labels must be the same length")
    return p, y


def reliability_bins(
    probs: list[float], labels: list[int], n_bins: int = 10
) -> tuple[list[ReliabilityBin], float]:
    """Return per-bin (mean predicted, observed, count) and the ECE (Deep Dive #4)."""
    p, y = _as_arrays(probs, labels)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins: list[ReliabilityBin] = []
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        mask = (p >= lo) & (p < hi) if hi < 1.0 else (p >= lo) & (p <= hi)
        if not mask.any():
            continue
        pred = float(p[mask].mean())
        obs = float(y[mask].mean())
        weight = float(mask.mean())
        ece += weight * abs(pred - obs)
        bins.append(ReliabilityBin(pred, obs, int(mask.sum())))
    return bins, ece


def brier_score(probs: list[float], labels: list[int]) -> float:
    """Mean squared error between probabilities and outcomes (lower is better)."""
    p, y = _as_arrays(probs, labels)
    return float(np.mean((p - y) ** 2))


def auc_score(probs: list[float], labels: list[int]) -> float:
    """Area under the ROC curve via the Mann-Whitney U statistic (rank-based).

    Returns 0.5 when all labels are identical (no discrimination is definable).
    """
    p, y = _as_arrays(probs, labels)
    pos = p[y == 1.0]
    neg = p[y == 0.0]
    if pos.size == 0 or neg.size == 0:
        return 0.5
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, p.size + 1)
    # Average ranks for ties so the statistic is exact.
    _assign_tie_ranks(p, ranks)
    rank_sum_pos = ranks[y == 1.0].sum()
    u = rank_sum_pos - pos.size * (pos.size + 1) / 2.0
    return float(u / (pos.size * neg.size))


def _assign_tie_ranks(values: NDArray[np.float64], ranks: NDArray[np.float64]) -> None:
    order = np.argsort(values, kind="mergesort")
    sorted_vals = values[order]
    i = 0
    n = values.size
    while i < n:
        j = i
        while j + 1 < n and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        if j > i:
            avg = (i + 1 + j + 1) / 2.0
            ranks[order[i : j + 1]] = avg
        i = j + 1


def base_rate(labels: list[int]) -> float:
    """Unconditional positive-listing rate over the sample."""
    if not labels:
        return 0.0
    return float(np.mean(labels))


def evaluate_reliability(
    probs: list[float], labels: list[int], n_bins: int = 10
) -> ReliabilityReport:
    """Compute the full reliability report (bins + ECE + Brier + AUC + base rate)."""
    bins, ece = reliability_bins(probs, labels, n_bins)
    return ReliabilityReport(
        bins=bins,
        ece=ece,
        brier=brier_score(probs, labels),
        auc=auc_score(probs, labels),
        base_rate=base_rate(labels),
        n=len(labels),
    )
