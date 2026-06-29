# Benchmark — Calibrated Model vs Subscription Rules

*Same walk-forward out-of-sample set, no tuning on the reported fold. APPLY precision = fraction of selected IPOs that listed positive net-of-cost. Engineering/research reference, not financial advice.*

Out-of-sample IPOs: **233** | model APPLY cutoff: 0.65

## APPLY precision (with Wilson 95% CI)

| Method | N selected | APPLY precision | 95% CI | Losers | Avg loss (net) |
|---|---|---|---|---|---|
| Apply to all (base rate) | 233 | 69.1% | [62.9%, 74.7%] | 72 | -6.5% |
| Apply if overall subscription > 1x | 227 | 70.5% | [64.2%, 76.0%] | 67 | -6.8% |
| Apply if QIB > 1x | 233 | 69.1% | [62.9%, 74.7%] | 72 | -6.5% |
| Top-N by QIB (equal selectivity) | 153 | 84.3% | [77.7%, 89.2%] | 24 | -8.5% |
| Model APPLY verdicts | 153 | 83.7% | [77.0%, 88.7%] | 25 | -7.6% |

## Model vs equal-selectivity QIB rule (the key head-to-head)

- Model APPLY precision: **83.7%** (N=153, CI [77.0%, 88.7%])
- Top-N-by-QIB precision: **84.3%** (N=153, CI [77.7%, 89.2%])
- Precision gap: **-0.7%** (CIs overlap heavily — not a real edge)

Paired view (only where the two disagree):
- IPOs only the model picks: 1 winners / 3 losers
- IPOs only the QIB rule picks: 2 winners / 2 losers

## Calibration — what the rules cannot do

The model emits an honest probability (OOS ECE **0.073**, Brier **0.164**, AUC **0.812**); the rules emit only yes/no, so they cannot tell you *how likely* — there is no calibration to report for them.

| Bin predicted | Observed | N |
|---|---|---|
| 0.38 | 0.41 | 27 |
| 0.45 | 0.37 | 38 |
| 0.53 | 0.44 | 9 |
| 0.66 | 0.57 | 14 |
| 0.74 | 0.75 | 16 |
| 0.87 | 0.75 | 59 |
| 0.92 | 0.97 | 70 |

## Loss profile (lower / smaller is better)

- Apply to all (base rate): 72 losers, avg net -6.5%, worst -96.7%
- Apply if overall subscription > 1x: 67 losers, avg net -6.8%, worst -96.7%
- Apply if QIB > 1x: 72 losers, avg net -6.5%, worst -96.7%
- Top-N by QIB (equal selectivity): 24 losers, avg net -8.5%, worst -96.7%
- Model APPLY verdicts: 25 losers, avg net -7.6%, worst -96.7%

## Regime split (does the QIB rule break in a cold market?)

| Year | N | Base rate | QIB>1x prec | Top-N-QIB prec | Model prec |
|---|---|---|---|---|---|
| 2022 | 14 | 57% | 57.1% | 80.0% | 80.0% |
| 2023 | 48 | 79% | 79.2% | 86.1% | 86.1% |
| 2024 | 70 | 74% | 74.3% | 83.0% | 83.0% |
| 2025 | 82 | 70% | 69.5% | 83.6% | 83.6% |
| 2026 | 19 | 32% | 31.6% | 75.0% | 75.0% |

**Coldest slice = 2026** (base rate 32%): model 75.0% (N=4) vs top-N-QIB 75.0% (N=4).

## Kill-flags on heavily-oversubscribed IPOs (QIB > 10x)

Of 193 heavily-oversubscribed mainboard IPOs, **0** tripped a kill-flag. In the official-only dataset the kill-flag inputs (final-days GMP slope, OFS fraction) are not yet populated, and SME issues are excluded upstream — so no kill-flag can fire here. Their loss-avoidance value is demonstrable only once Phase 5 (GMP) and OFS enrichment land.