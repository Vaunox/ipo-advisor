# Deep Dive #3 — The Scoring Model

*The design rationale behind the verdict engine: the weighted-then-calibrated structure, the weight philosophy, the kill-flags, the verdict mapping, and the reason generator. The working code is `ipo_advisor.py`; this document explains the *why* a builder needs in order to tune it without breaking it. Grounded June 2026.*

---

## Why weighted-then-calibrated, not a black box

The product promise is **grounded and confident**. A gradient-boosted black box on ~100 IPOs would be neither: it would overfit a tiny sample and its "reasons" would be post-hoc. A transparent weighted score gives:

- **Traceability** — every point of the score is a named feature contribution, so the reason string is the model's actual arithmetic, not a narrative bolted on after.
- **Tunability** — a builder can reason about and adjust one weight at a time.
- **A clean calibration seam** — the raw score is a single scalar that the Phase 4 calibrator maps to an honest probability.

The pipeline is deliberately: **features → weighted score → calibrated probability → threshold → verdict; reason from contributions; kill-flags can override.** One path, defensible end to end.

---

## The weight philosophy (these are priors, to be tuned in Phase 4)

The starting weights encode a thesis, not a measurement — Phase 4 fits them against outcomes. The thesis:

- **GMP is the dominant *direction* signal** (highest positive weight) because it is the single most-watched read on listing-day demand — but it is unofficial and ~70–75% directionally accurate, so it sets the sign, not the certainty.
- **QIB > NII > retail** in confidence weight: institutions price with real capital and lock-in; retail partly echoes GMP, so it earns the least.
- **Anchor quality** is a meaningful positive — a marquee, long-lock-in anchor book is hard to fake.
- **Valuation is a negative *brake*, not a driver.** Aggressive pricing caps the pop; it rarely creates one. So it can pull a score down but never carries it up. This is the answer to "why not full valuation machinery" — for a listing-day flip, valuation is a ceiling, not an engine.
- **OFS** is a mild negative (promoter cash-out); **regime** a modest context term.

Keep every weight in config. The Phase 4 report justifies the fitted values; until then they are honest priors clearly labelled as such.

---

## Kill-flags — why overrides live outside the score

Some conditions should veto an issue regardless of how good the score looks, because they signal a *different kind* of risk than the score measures:

- **SME segment** — manipulation + SEBI-scrutiny risk; excluded or hard-penalized upstream anyway.
- **Collapsing GMP in the final days** — demand evaporating at the worst moment; a high level two days ago doesn't save it.
- **Near-total OFS** — no fresh capital, pure promoter exit.
- **Material promoter litigation** — tail risk the listing-day model can't price.

A kill-flag forces `SKIP` and says so in the reason ("Kill-flag override despite P=72%…"). Keeping them separate from the weighted sum is deliberate: a structurally bad issue should not be rescued by a strong GMP. Thresholds (e.g. how negative a GMP slope counts as "collapsing") live in config and are sanity-checked in Phase 4, not tuned to maximize backtest return (that would defeat their purpose).

---

## Verdict mapping and abstention

On the **calibrated** probability:
- `P ≥ APPLY_CUTOFF` → **APPLY**
- `MARGINAL_CUTOFF ≤ P < APPLY_CUTOFF` → **MARGINAL**
- `P < MARGINAL_CUTOFF` → **SKIP**
- any kill-flag → **SKIP** (override)
- missing critical feature or unclosed book → **INSUFFICIENT_SIGNAL** (checked *before* scoring)

Cutoffs are product decisions (chosen in Phase 4 to hit an APPLY-precision target), kept in config — not fitted parameters. Abstention is checked first so a blind record can never reach the threshold logic.

---

## The reason generator (grounded by construction)

Sort the feature contributions by absolute magnitude; template the top ~3 positives into the reason and the top ~2 negatives into "watch"; append any kill-flags. Because the text is generated *from the same numbers that produced the score*, it cannot drift from the verdict — there is no separate narrative to get out of sync. Cite values, not adjectives: "QIB 38×, GMP +32% holding," not "strong demand."

---

## The overconfidence trap (read before shipping)

The placeholder `calibrate()` is a bare logistic squash; in the demo it printed **99%** for a strong IPO. That number is meaningless — it reflects the squash, not reality. **No probability is shown to a user until Phase 4's calibrator replaces it and passes the reliability gate.** Until then the engine may show the verdict with an explicit "uncalibrated — not for decisions" banner. This is the line between asserting confidence and earning it.

**Output contract of Layer 3:** `evaluate(features) → Verdict{verdict, probability, reason, watch, kill_flags}`, with probability sourced from the calibrated model and abstention/override paths honored.

---

## Open questions to settle while building

- **Expose probability early, or verdict-only until calibrated?** Recommended: verdict-only (banner) pre-Phase-4, full probability after the gate.
- **Cutoff values:** set by the APPLY-precision target in Phase 4.
- **Kill-flag thresholds:** the GMP-collapse slope and the "near-total" OFS level — sanity bounds, reviewed not return-optimized.

---

*This is an engineering/research reference, not financial advice. A calibrated probability is an estimate, not an assurance.*
