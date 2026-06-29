"""Grounded reason generator (Layer 3, Deep Dive #3).

The reason text is generated *from the same numbers that produced the score*, so it
can never drift from the verdict. It cites values, not adjectives ("QIB 203×, GMP
+30% holding", not "strong demand"). Top positive contributions become the reason;
top negatives become watch-items; kill-flags and the uncalibrated banner are
appended.

Until the Phase-4 calibrator passes the reliability gate, the banner makes the
honesty explicit: the verdict may be shown, but the probability is not for
decisions (Deep Dive #3, "the overconfidence trap").
"""

from __future__ import annotations

from ipo.core.types import IPOFeatures

UNCALIBRATED_BANNER = "UNCALIBRATED — not for decisions (placeholder calibrator)"

_MAX_POSITIVE = 3
_MAX_WATCH = 2


def _cite(name: str, features: IPOFeatures) -> str | None:
    """Render one feature's human-readable citation from its raw value."""
    f = features
    match name:
        case "gmp_level" if f.gmp_level is not None:
            return f"GMP +{f.gmp_level:.0f}%"
        case "gmp_slope" if f.gmp_slope is not None:
            return f"GMP slope {f.gmp_slope:+.0f}%"
        case "qib_sub" if f.qib_sub is not None:
            return f"QIB {f.qib_sub:.0f}×"
        case "nii_sub" if f.nii_sub is not None:
            return f"NII {f.nii_sub:.0f}×"
        case "retail_sub" if f.retail_sub is not None:
            return f"retail {f.retail_sub:.0f}×"
        case "anchor_quality" if f.anchor_quality is not None:
            return f"anchor quality {f.anchor_quality:.2f}"
        case "relative_valuation" if f.relative_valuation is not None:
            return f"valuation {f.relative_valuation:.2f}× peers"
        case "ofs_fraction" if f.ofs_fraction is not None:
            return f"OFS {f.ofs_fraction * 100:.0f}%"
        case "market_regime" if f.market_regime is not None:
            return f"regime {f.market_regime:+.2f}"
        case _:
            return None


def generate_reason(
    features: IPOFeatures,
    contributions: dict[str, float],
    kill_flags: list[str],
    *,
    calibrated: bool,
    probability: float | None,
) -> tuple[str, list[str]]:
    """Return ``(reason, watch)`` grounded in the actual contributions.

    Args:
        features: the raw feature vector (for value citations).
        contributions: signed per-feature contributions from the scorer.
        kill_flags: any triggered kill-flags (force SKIP).
        calibrated: whether the calibrator has passed the reliability gate.
        probability: the (calibrated) probability, cited only when ``calibrated``.
    """
    ordered = sorted(contributions.items(), key=lambda kv: abs(kv[1]), reverse=True)
    positives = [name for name, val in ordered if val > 0]
    negatives = [name for name, val in ordered if val < 0]

    reason_cites = [c for name in positives[:_MAX_POSITIVE] if (c := _cite(name, features))]
    watch = [c for name in negatives[:_MAX_WATCH] if (c := _cite(name, features))]

    if "no_listed_peer" in features.flags:
        watch.append("no listed peer to anchor valuation")

    parts: list[str] = []
    if not calibrated:
        parts.append(UNCALIBRATED_BANNER)

    if kill_flags:
        prob_note = (
            f" despite P={probability:.0%}" if calibrated and probability is not None else ""
        )
        parts.append(f"Kill-flag override{prob_note}: {', '.join(kill_flags)}")
    elif reason_cites:
        prefix = f"P={probability:.0%}. " if calibrated and probability is not None else ""
        parts.append(f"{prefix}Driven by {', '.join(reason_cites)}")
    else:
        parts.append("No positive signal among available features")

    return " | ".join(parts), watch
