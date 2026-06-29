"""Placeholder calibrator — plumbing only, NOT FOR RELEASE (Deep Dive #3/#4).

A bare logistic squash of the raw score. It discriminates a little and is calibrated
not at all — in the original demo this kind of squash printed a meaningless 99%.
``passes_reliability_gate`` is therefore hard-wired ``False``: Layer 3 must not show
its probability to a user. The real, persisted calibrator from Phase 4 replaces this
only after the reliability gate passes (Inviolable Rule 1).
"""

from __future__ import annotations

import math

PLACEHOLDER_VERSION = "placeholder-logistic-0 (NOT FOR RELEASE)"


class PlaceholderCalibrator:
    """Logistic squash standing in for the real calibrator until Phase 4."""

    version = PLACEHOLDER_VERSION

    def fit(self, raw_scores: list[float], labels: list[int]) -> None:
        """No-op: the placeholder is not fitted (it is replaced in Phase 4)."""
        return None

    def predict_proba(self, raw_score: float) -> float:
        """Return ``sigmoid(raw_score)`` — an UNCALIBRATED number, never user-facing."""
        return 1.0 / (1.0 + math.exp(-raw_score))

    @property
    def passes_reliability_gate(self) -> bool:
        """Always ``False``: an uncalibrated number must never be shown (Rule 1)."""
        return False
