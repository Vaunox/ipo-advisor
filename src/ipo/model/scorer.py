"""Transparent weighted scorer (Layer 3, Deep Dive #3).

Every point of the raw score is a named feature contribution, so the reason string
is the model's actual arithmetic — not a narrative bolted on afterwards. Weights are
positive magnitudes in config; this module owns each feature's **sign semantics**:

* add (good for the pop): GMP level, GMP slope, QIB/NII/retail, anchor, regime;
* subtract (brakes): relative valuation (only when pricier than peers) and OFS.

Normalization (winsorize + saturating maps) is applied here on the raw, human-
readable feature values (Deep Dive #2 recipes), so each issue is scored on its own
absolute signals. The single raw scalar is the clean seam the Phase-4 calibrator
maps to an honest probability. Optional features that are ``None`` are dropped
(treated neutral); a missing *critical* feature is caught upstream by abstention.
"""

from __future__ import annotations

from ipo.core.config import FeaturesConfig
from ipo.core.types import IPOFeatures
from ipo.features.normalize import clamp, saturate, signed_saturate, winsorize

# Max over-pricing (issue P/E vs peer median) that the valuation brake counts, so one
# extreme ratio can't dominate. 1.0 == priced 100% above peers.
_VALUATION_OVERPRICING_CAP = 1.0


class WeightedScorer:
    """Weighted-sum scorer over normalized feature values (implements ScoringModel)."""

    def __init__(self, weights: dict[str, float], features_config: FeaturesConfig) -> None:
        """Bind the (positive-magnitude) weights and the normalization config."""
        self._w = weights
        self._cfg = features_config

    def _weight(self, name: str) -> float:
        return self._w.get(name, 0.0)

    def contributions(self, features: IPOFeatures) -> dict[str, float]:
        """Return each feature's signed contribution to the raw score (named, traceable)."""
        c: dict[str, float] = {}
        gmp = self._cfg.gmp
        sub = self._cfg.subscription

        if features.gmp_level is not None:
            level = winsorize(features.gmp_level, 0.0, gmp.winsor_max_pct)
            c["gmp_level"] = self._weight("gmp_level") * saturate(level, gmp.saturation_scale_pct)
        if features.gmp_slope is not None:
            c["gmp_slope"] = self._weight("gmp_slope") * signed_saturate(
                features.gmp_slope, gmp.slope_scale_pct
            )
        for name, value in (
            ("qib_sub", features.qib_sub),
            ("nii_sub", features.nii_sub),
            ("retail_sub", features.retail_sub),
        ):
            if value is not None:
                mult = winsorize(value, 0.0, sub.winsor_max_x)
                c[name] = self._weight(name) * saturate(mult, sub.saturation_scale_x)
        if features.anchor_quality is not None:
            c["anchor_quality"] = self._weight("anchor_quality") * features.anchor_quality
        if features.relative_valuation is not None:
            overpricing = clamp(features.relative_valuation - 1.0, 0.0, _VALUATION_OVERPRICING_CAP)
            c["relative_valuation"] = -self._weight("relative_valuation") * overpricing
        if features.ofs_fraction is not None:
            c["ofs_fraction"] = -self._weight("ofs_fraction") * features.ofs_fraction
        if features.market_regime is not None:
            c["market_regime"] = self._weight("market_regime") * features.market_regime
        return c

    def score(self, features: IPOFeatures) -> float:
        """Return the raw (uncalibrated) score: the sum of feature contributions."""
        return sum(self.contributions(features).values())
