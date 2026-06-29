# Regime Fix — wiring in market_regime, measured out-of-sample

*Walk-forward OOS only: the regime feature is a deterministic transform of past Nifty (no fit); the calibrator is fit on past folds; the regime weight is the config prior (0.10), not tuned to the cold slice. ECE tolerance = 0.1. Not financial advice.*

## Cold slice — before vs after (the question)

| Metric | Before (official-only) | After (regime-aware) |
|---|---|---|
| Cold ECE | 0.102 | **0.139** |
| Cold APPLY precision | 83% [70%,91%] (N=105, APPLY=48) | 87% [73%,94%] (N=105, APPLY=39) |

## Hot slice — sanity (should not break)

| Metric | Before | After |
|---|---|---|
| Hot ECE | 0.077 | 0.072 |
| Hot APPLY precision | 85% [79%,90%] (N=193, APPLY=143) | 84% [77%,89%] (N=193, APPLY=145) |

## Per-regime calibration (fallback — single model didn't converge cold)

- Cold ECE (per-regime calibrators): **0.115** | cold APPLY 86% [73%,93%] (N=105, APPLY=43)
- Per-block **cold training-fold sizes**: [13, 15, 16, 35, 36, 39, 44, 44, 44, 50, 70, 76, 82, 95, 95] (min usable = 20; 3 blocks fell back to pooled).
- A cold fold below ~20 can't calibrate a separate curve — judge from those Ns.

## H1 2022 (flagged, uninformative — N=12, not tuned to)

- Cold-correction sub-period: ECE 0.495, APPLY 100% [21%,100%] (N=12, APPLY=1). Too thin to read.

## Outcome

**Cold probability STILL does not calibrate. Correct outcome: GATE/FLAG APPLY as 'cold-market — ranking reliable, probability less certain'; do not force the number.**

The *ranking* edge was already regime-robust (cold APPLY precision well above the cold base rate). This step is purely about whether the *probability* calibrates in cold markets out-of-sample. APPLY cutoff = config 0.65; nothing was tuned to the reported slice.