"""The calibrator — raw score -> trustworthy probability (Deep Dive #4, Module D).

Two small-sample-honest choices, both implementing the ``Calibrator`` protocol:

* ``PlattCalibrator`` — a 2-parameter sigmoid (logistic) fit by Newton-Raphson.
  Robust on ~100 IPOs; the default (Deep Dive #4).
* ``IsotonicCalibrator`` — non-parametric pool-adjacent-violators; more flexible,
  data-hungry. Use only with a few hundred labelled IPOs.

A calibrator is trusted only once ``passes_reliability_gate`` is set True by the
backtest (Inviolable Rule 1). It is persisted **versioned** with the feature-code
hash and the label definition so a verdict is always reproducible.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_MAX_NEWTON_ITERS = 100
_CONVERGENCE = 1e-9


@dataclass
class CalibratorMeta:
    """Provenance pinned to a fitted calibrator (Deep Dive #4: reproducibility)."""

    feature_code_hash: str
    label_definition: str
    sample_size: int
    base_rate: float


def feature_code_hash(*sources: str) -> str:
    """Hash the feature-construction source(s) so a calibrator pins the code that fed it."""
    digest = hashlib.sha256()
    for src in sources:
        digest.update(src.encode("utf-8"))
    return digest.hexdigest()[:16]


class PlattCalibrator:
    """2-parameter sigmoid calibrator: P = sigmoid(a*score + b)."""

    def __init__(self, *, version: str = "platt-1") -> None:
        """Create an unfitted Platt calibrator pinned to ``version``."""
        self.version = version
        self._a = 0.0
        self._b = 0.0
        self._fitted = False
        self._gate = False
        self.meta: CalibratorMeta | None = None

    def fit(self, raw_scores: list[float], labels: list[int]) -> None:
        """Fit (a, b) by Newton-Raphson on (score, label) pairs (deterministic)."""
        x = np.asarray(raw_scores, dtype=np.float64)
        y = np.asarray(labels, dtype=np.float64)
        if x.size == 0:
            raise ValueError("cannot fit on an empty sample")
        a, b = 0.0, 0.0
        for _ in range(_MAX_NEWTON_ITERS):
            p = 1.0 / (1.0 + np.exp(-(a * x + b)))
            w = np.clip(p * (1.0 - p), 1e-9, None)
            g_a = float(np.sum((p - y) * x))
            g_b = float(np.sum(p - y))
            h_aa = float(np.sum(w * x * x))
            h_ab = float(np.sum(w * x))
            h_bb = float(np.sum(w))
            det = h_aa * h_bb - h_ab * h_ab
            if abs(det) < 1e-12:
                break
            da = (h_bb * g_a - h_ab * g_b) / det
            db = (-h_ab * g_a + h_aa * g_b) / det
            a -= da
            b -= db
            if abs(da) + abs(db) < _CONVERGENCE:
                break
        self._a, self._b = float(a), float(b)
        self._fitted = True

    def predict_proba(self, raw_score: float) -> float:
        """Return the calibrated P(positive listing) for one raw score."""
        if not self._fitted:
            raise RuntimeError("calibrator is not fitted")
        return float(1.0 / (1.0 + np.exp(-(self._a * raw_score + self._b))))

    @property
    def passes_reliability_gate(self) -> bool:
        """True only once the backtest has validated calibration (Rule 1)."""
        return self._gate

    def set_gate(self, passed: bool) -> None:
        """Record the reliability-gate outcome (set by the backtest)."""
        self._gate = passed

    def params(self) -> dict[str, float]:
        """Return the fitted parameters (for persistence)."""
        return {"a": self._a, "b": self._b}


class IsotonicCalibrator:
    """Non-parametric isotonic (pool-adjacent-violators) calibrator."""

    def __init__(self, *, version: str = "isotonic-1") -> None:
        """Create an unfitted isotonic calibrator pinned to ``version``."""
        self.version = version
        self._x = np.empty(0)
        self._y = np.empty(0)
        self._fitted = False
        self._gate = False
        self.meta: CalibratorMeta | None = None

    def fit(self, raw_scores: list[float], labels: list[int]) -> None:
        """Fit a monotone step function via pool-adjacent-violators."""
        x = np.asarray(raw_scores, dtype=np.float64)
        y = np.asarray(labels, dtype=np.float64)
        if x.size == 0:
            raise ValueError("cannot fit on an empty sample")
        order = np.argsort(x, kind="mergesort")
        xs, ys = x[order], y[order]
        # PAV: maintain blocks of (sum, weight, value); merge while non-monotone.
        values = list(ys)
        weights = [1.0] * len(ys)
        i = 0
        while i < len(values) - 1:
            if values[i] > values[i + 1]:
                total = values[i] * weights[i] + values[i + 1] * weights[i + 1]
                wsum = weights[i] + weights[i + 1]
                values[i] = total / wsum
                weights[i] = wsum
                del values[i + 1]
                del weights[i + 1]
                # group the x-thresholds in lockstep
                xs = np.delete(xs, i + 1)
                if i > 0:
                    i -= 1
            else:
                i += 1
        self._x = xs
        self._y = np.asarray(values, dtype=np.float64)
        self._fitted = True

    def predict_proba(self, raw_score: float) -> float:
        """Return the calibrated probability by stepwise lookup (clamped at the ends)."""
        if not self._fitted:
            raise RuntimeError("calibrator is not fitted")
        idx = int(np.searchsorted(self._x, raw_score, side="right")) - 1
        idx = max(0, min(idx, self._y.size - 1))
        return float(self._y[idx])

    @property
    def passes_reliability_gate(self) -> bool:
        """True only once the backtest has validated calibration (Rule 1)."""
        return self._gate

    def set_gate(self, passed: bool) -> None:
        """Record the reliability-gate outcome (set by the backtest)."""
        self._gate = passed

    def params(self) -> dict[str, list[float]]:
        """Return the fitted thresholds/values (for persistence)."""
        return {"x": self._x.tolist(), "y": self._y.tolist()}


def make_calibrator(method: str) -> PlattCalibrator | IsotonicCalibrator:
    """Build an unfitted calibrator for the configured ``method``."""
    if method == "platt":
        return PlattCalibrator()
    if method == "isotonic":
        return IsotonicCalibrator()
    raise ValueError(f"unknown calibration method: {method}")


def save_calibrator(
    calibrator: PlattCalibrator | IsotonicCalibrator, path: Path, *, meta: CalibratorMeta
) -> None:
    """Persist a fitted calibrator with its provenance, versioned (Deep Dive #4)."""
    method = "platt" if isinstance(calibrator, PlattCalibrator) else "isotonic"
    payload = {
        "method": method,
        "version": calibrator.version,
        "params": calibrator.params(),
        "passes_reliability_gate": calibrator.passes_reliability_gate,
        "meta": {
            "feature_code_hash": meta.feature_code_hash,
            "label_definition": meta.label_definition,
            "sample_size": meta.sample_size,
            "base_rate": meta.base_rate,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_calibrator(path: Path) -> PlattCalibrator | IsotonicCalibrator:
    """Load a persisted calibrator (restoring params and the gate flag)."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    method = payload["method"]
    params = payload["params"]
    cal: PlattCalibrator | IsotonicCalibrator
    if method == "platt":
        cal = PlattCalibrator(version=payload["version"])
        cal._a = float(params["a"])
        cal._b = float(params["b"])
    else:
        cal = IsotonicCalibrator(version=payload["version"])
        cal._x = np.asarray(params["x"], dtype=np.float64)
        cal._y = np.asarray(params["y"], dtype=np.float64)
    cal._fitted = True
    cal.set_gate(bool(payload["passes_reliability_gate"]))
    return cal
