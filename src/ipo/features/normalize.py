"""Normalization recipes (Deep Dive #2, "Normalization philosophy").

Pure, side-effect-free transforms shared by feature construction and the scorer:

* ``winsorize`` — clip a raw input at sensible caps so one bad scraped print can't
  swing a verdict.
* ``saturate`` — ``1 - exp(-x/scale)`` for unbounded positives (GMP, subscription),
  so extremes compress rather than dominate.
* ``signed_saturate`` — ``tanh(x/scale)`` for signed quantities (e.g. GMP slope),
  mapping to ``(-1, 1)``.
* ``clamp`` — bound a value to ``[lo, hi]``.

These do not standardize across IPOs: each issue is scored on its own absolute
signals (Deep Dive #2).
"""

from __future__ import annotations

import math


def clamp(x: float, lo: float, hi: float) -> float:
    """Return ``x`` bounded to ``[lo, hi]``."""
    if lo > hi:
        raise ValueError("lo must be <= hi")
    return max(lo, min(hi, x))


def winsorize(x: float, lo: float, hi: float) -> float:
    """Clip ``x`` to ``[lo, hi]`` (alias of clamp, named for intent at input boundaries)."""
    return clamp(x, lo, hi)


def saturate(x: float, scale: float) -> float:
    """Map a non-negative ``x`` to ``[0, 1)`` with diminishing returns past ``scale``.

    Negative inputs map to ``0.0`` (this transform is for positive magnitudes).
    """
    if scale <= 0:
        raise ValueError("scale must be > 0")
    if x <= 0:
        return 0.0
    return 1.0 - math.exp(-x / scale)


def signed_saturate(x: float, scale: float) -> float:
    """Map a signed ``x`` to ``(-1, 1)`` via ``tanh(x/scale)`` (sign preserved)."""
    if scale <= 0:
        raise ValueError("scale must be > 0")
    return math.tanh(x / scale)
