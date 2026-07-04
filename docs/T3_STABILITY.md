# T+3 cross-break calibration stability (A4)

*Does the calibrated model behave differently across the SEBI T+6->T+3 listing-timeline cutover (mandatory **2023-12-01**)? Walk-forward out-of-sample rows, split by the `t3_regime` dummy. A **read-only reported check** — the dummy is never added to the score and the calibrator is never refit. Engineering/research reference, not financial advice.*

**Verdict: STABLE - ECE shift within tolerance and APPLY-precision CIs overlap; the calibrator holds across the break**

| slice | n | base rate | APPLY precision @ 0.65 (95% CI) | ECE |
|---|---|---|---|---|
| pre-T+3 (< 2023-12-01) | 52 | 73% | 87% (95% CI 71%-95%, n=31) | 0.098 |
| post-T+3 (>= 2023-12-01) | 181 | 68% | 83% (95% CI 75%-88%, n=122) | 0.089 |

ECE shift across the break: **-0.009** (tolerance 0.030).

*Honest caveat:* the smaller of the two slices carries the wider confidence interval, so a STABLE read means no cross-break difference is **detectable** at this sample size, not that none exists. Re-run as more post-T+3 outcomes accrue; if a real difference emerges, the action is an operator recalibration on post-cutover data, not a silent change here.
