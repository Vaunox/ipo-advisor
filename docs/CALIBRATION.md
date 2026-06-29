# Calibration Report (Phase 4)

*The artifact that earns the right to show probabilities. Official-only model (GMP added in Phase 5). This is an engineering/research reference, not financial advice.*

- **Calibrator:** platt | feature-code hash `d01815d61aec4d33`
- **Label definition:** `net_of_cost(listing_open) > 0`
- **Sample size (scored, OOS-eligible):** 293
- **Base rate (positive net listing):** 69.1%
- **OOS AUC:** 0.812 | **ECE:** 0.073 | **Brier:** 0.164
- **APPLY precision (cutoff 0.65):** 83.7%
- **Look-ahead shuffled AUC:** 0.472 (must be ~0.5)

## Reliability gate: PASSED

| Check | Result | Detail |
|---|---|---|
| discrimination | PASS | OOS AUC=0.812 (floor 0.55) |
| calibration | PASS | ECE=0.073 (bound 0.1) |
| beats_base_rate | PASS | APPLY precision=0.837 vs base rate 0.691 + 0.05 |
| time_stable | PASS | early ECE=0.110, late ECE=0.087 (bound 0.150) |
| look_ahead_collapses | PASS | shuffled-label AUC=0.472 (must be ~0.5) |
| abstention_excluded | PASS | INSUFFICIENT_SIGNAL cases are excluded from scored metrics by construction |

## Reliability diagram (predicted vs observed)

| Bin mean predicted | Observed rate | Count |
|---|---|---|
| 0.38 | 0.41 | 27 |
| 0.45 | 0.37 | 38 |
| 0.53 | 0.44 | 9 |
| 0.66 | 0.57 | 14 |
| 0.74 | 0.75 | 16 |
| 0.87 | 0.75 | 59 |
| 0.92 | 0.97 | 70 |

## Honest posture (Deep Dive #4)

~293 mainboard IPOs is a small sample: per-bucket confidence intervals are wide. State the sample size and base rate next to every probability; recalibrate quarterly and after regime shifts. A calibrated 70% still fails ~30% of the time.

If the gate did not pass, the official-only signal is insufficient on its own — proceed to Phase 5 (GMP) and re-evaluate; until then Layer 3 shows the verdict with the uncalibrated banner and withholds the probability.
