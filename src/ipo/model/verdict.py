"""Verdict engine — the Layer-3 output contract (Deep Dive #3).

``evaluate`` is the one defensible path: abstain if blind, else score → calibrate →
threshold → verdict, with kill-flags able to override to SKIP and the reason
generated from the same contributions. Order matters:

1. **Abstention first** — a missing critical feature or an unclosed book yields
   ``INSUFFICIENT_SIGNAL`` *before* any scoring, so a blind record never reaches the
   threshold logic and never produces a number (Inviolable Rule 3).
2. **Kill-flags** force ``SKIP`` regardless of probability (Inviolable Rule 4).
3. **Thresholds** on the calibrated probability map to APPLY / MARGINAL / SKIP.

The probability is shown only if the calibrator has passed the reliability gate;
otherwise the verdict carries ``probability=None`` and an uncalibrated banner
(Inviolable Rule 1 / Deep Dive #3 "overconfidence trap").
"""

from __future__ import annotations

from ipo.core.config import AppConfig, VerdictThresholds
from ipo.core.interfaces import Calibrator, ScoringModel
from ipo.core.types import IPOFeatures, IPORecord, Verdict, VerdictType
from ipo.model.killflags import kill_flags
from ipo.model.reason import generate_reason


def missing_critical(features: IPOFeatures, critical: list[str]) -> list[str]:
    """Return the critical features that are absent (or the unclosed-book marker)."""
    missing = [name for name in critical if getattr(features, name, None) is None]
    if not features.book_closed:
        missing.append("book_closed")
    return missing


def map_probability(probability: float, apply_cutoff: float, marginal_cutoff: float) -> VerdictType:
    """Map a probability to APPLY / MARGINAL / SKIP on the configured cutoffs."""
    if probability >= apply_cutoff:
        return VerdictType.APPLY
    if probability >= marginal_cutoff:
        return VerdictType.MARGINAL
    return VerdictType.SKIP


# Graded cold-market caveats per regime tier (v2 B9). The 'cold' text is unchanged from the binary
# flag (the UI keys on "cold market"); 'soft' is the milder middle tier. 'normal' → no caveat.
_REGIME_CAVEAT: dict[str, str] = {
    "soft": "softening market — ranking reliable, probability a touch less certain",
    "cold": "cold market — ranking reliable, probability less certain",
}


def regime_tier(market_regime: float | None, thresholds: VerdictThresholds) -> str:
    """Grade the point-in-time market_regime into ``'normal' | 'soft' | 'cold'`` (v2 B9).

    Annotation-only — ``market_regime``'s scorer weight is 0, so the tier only selects a graded
    cold-market caveat, never a score change. Boundaries are untuned round numbers
    (``soft_regime_flag`` / ``cold_regime_flag``), chosen a-priori and NOT fit to listing outcomes.
    ``None`` (no regime history) grades as ``'normal'`` — no caveat.
    """
    if market_regime is None or market_regime > thresholds.soft_regime_flag:
        return "normal"
    if market_regime <= thresholds.cold_regime_flag:
        return "cold"
    return "soft"


def evaluate(
    record: IPORecord,
    features: IPOFeatures,
    *,
    scorer: ScoringModel,
    calibrator: Calibrator,
    config: AppConfig,
) -> Verdict:
    """Evaluate one IPO into a complete ``Verdict`` (abstention/override honored)."""
    # 1. Abstention — checked before scoring so a blind record never gets a number.
    missing = missing_critical(features, config.features.critical_features)
    if missing:
        return Verdict(
            ipo_id=features.ipo_id,
            verdict=VerdictType.INSUFFICIENT_SIGNAL,
            probability=None,
            reason=f"INSUFFICIENT_SIGNAL: missing {', '.join(missing)}",
            watch=[],
            kill_flags=[],
        )

    # 2. Score and (placeholder-)calibrate.
    raw = scorer.score(features)
    probability = calibrator.predict_proba(raw)
    contributions = scorer.contributions(features)
    calibrated = calibrator.passes_reliability_gate

    # 3. Kill-flags override; else threshold the probability.
    flags = kill_flags(record, features, config.killflags)
    if flags:
        verdict = VerdictType.SKIP
    else:
        verdict = map_probability(
            probability,
            config.verdict_thresholds.apply,
            config.verdict_thresholds.marginal,
        )

    reason, watch = generate_reason(
        features,
        contributions,
        flags,
        calibrated=calibrated,
        probability=probability,
    )

    # Regime stress-test outcome: in an adverse market the *ranking* is reliable but the
    # *probability* does not calibrate out-of-sample, so flag rather than force it. Graded into
    # normal/soft/cold tiers (v2 B9) — annotation-only (weight 0); the number is never touched.
    caveat = _REGIME_CAVEAT.get(regime_tier(features.market_regime, config.verdict_thresholds))
    if caveat is not None:
        watch.append(caveat)

    return Verdict(
        ipo_id=features.ipo_id,
        verdict=verdict,
        probability=probability if calibrated else None,
        reason=reason,
        watch=watch,
        kill_flags=flags,
    )
