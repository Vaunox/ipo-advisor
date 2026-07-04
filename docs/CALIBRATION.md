# Calibration Report (Phase 4)

*The artifact that earns the right to show probabilities. Official-only model (GMP added in Phase 5). This is an engineering/research reference, not financial advice.*

- **Calibrator:** platt | feature-code hash `d01815d61aec4d33`
- **Label definition:** `net_of_cost(listing_open) > 0`
- **Sample size (scored, OOS-eligible):** 358
- **Base rate (positive net listing):** 69.8%
- **OOS AUC:** 0.797 | **ECE:** 0.081 | **Brier:** 0.170
- **APPLY precision (cutoff 0.65):** 84.8%
- **Look-ahead shuffled AUC:** 0.477 (must be ~0.5)

## Reliability gate: PASSED

| Check | Result | Detail |
|---|---|---|
| discrimination | PASS | OOS AUC=0.797 (floor 0.55) |
| calibration | PASS | ECE=0.081 (bound 0.1) |
| beats_base_rate | PASS | APPLY precision=0.848 vs base rate 0.698 + 0.05 |
| time_stable | PASS | early ECE=0.136, late ECE=0.056 (bound 0.150) |
| look_ahead_collapses | PASS | shuffled-label AUC=0.477 (must be ~0.5) |
| abstention_excluded | PASS | INSUFFICIENT_SIGNAL cases are excluded from scored metrics by construction |

## Reliability diagram (predicted vs observed)

| Bin mean predicted | Observed rate | Count |
|---|---|---|
| 0.08 | 1.00 | 1 |
| 0.16 | 0.22 | 9 |
| 0.26 | 0.53 | 15 |
| 0.34 | 0.40 | 53 |
| 0.44 | 0.37 | 19 |
| 0.58 | 1.00 | 4 |
| 0.65 | 0.50 | 12 |
| 0.73 | 0.71 | 14 |
| 0.86 | 0.61 | 33 |
| 0.95 | 0.93 | 138 |

## Honest posture (Deep Dive #4)

~358 mainboard IPOs is a small sample: per-bucket confidence intervals are wide. State the sample size and base rate next to every probability; recalibrate quarterly and after regime shifts. A calibrated 70% still fails ~30% of the time.

If the gate did not pass, the official-only signal is insufficient on its own — proceed to Phase 5 (GMP) and re-evaluate; until then Layer 3 shows the verdict with the uncalibrated banner and withholds the probability.
