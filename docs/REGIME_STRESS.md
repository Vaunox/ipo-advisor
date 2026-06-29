# Regime Stress-Test — does the model's edge survive cold markets?

*Walk-forward out-of-sample, full Phase-4 discipline: calibrator fit on held-out
folds, threshold = config 0.65 (never chosen on any reported slice), nothing tuned to
flatter the cold numbers. Cold ≡ Nifty negative 3-month trend or drawdown at listing.
Per-bucket Ns are shown so thin cells are visible. Engineering/research reference, not
financial advice.*

## Stage 1 — existing sample (2021+, 233 OOS IPOs)

| Regime | N | Base | AUC | ECE | APPLY N | APPLY prec | 95% CI | ~70% obs/N |
|---|---|---|---|---|---|---|---|---|
| All (overall) | 233 | 69% | 0.81 | 0.073 | 153 | 84% | [77%, 89%] | 67% / 30 |
| Hot (Nifty up 3m) | 156 | 73% | 0.82 | 0.062 | 116 | 84% | [76%, 89%] | 61% / 18 |
| **Cold** (neg 3m trend/drawdown) | 77 | 61% | 0.79 | 0.131 | 37 | **84%** | [69%, 92%] | 75% / 12 |
| Cold sub-period H1 2022 | 0 | — | — | — | — | — | — | (in training window, no OOS) |

The 2021+ window has no true bear, so "cold" here is mild (mainly the 2022 dip). H1 2022
fell entirely inside the walk-forward training window → no OOS rows. Hence Stage 2.

## Stage 2 — expanded sample back to 2017 (298 OOS IPOs; adds 2018–19 bear + 2020 COVID)

Official NSE backfill extended to 2017 (subscription works back to 2019; bhavcopy labels
to 2017). **75 new IPOs** from 2017–2020 (2017=30, 2018=21, 2019=12, 2020=12).

| Regime | N | Base | AUC | ECE | APPLY N | APPLY prec | 95% CI | ~70% obs/N |
|---|---|---|---|---|---|---|---|---|
| All (overall) | 298 | 70% | 0.80 | 0.081 | 191 | 85% | [79%, 89%] | 62% / 26 |
| Hot (Nifty up 3m) | 193 | 75% | 0.80 | 0.077 | 143 | 85% | [79%, 90%] | 57% / 14 |
| **Cold** (neg 3m trend/drawdown) | 105 | 60% | 0.76 | 0.102 | 48 | **83%** | [70%, 91%] | 83% / 6 |
| **Cold sub-period H1 2022** | 12 | 58% | **0.60** | **0.411** | 2 | **50%** | [9%, 91%] | — / 0 |

## Data cross-check (you asked for it)

Our **official NSE** QIB subscription was cross-checked against the independent
**skworld Kaggle** dataset: **268 IPOs matched, QIB agrees within 5% on 97% (261/268)**.
The official data is corroborated.

## The honest conclusion

**The model's *ranking/selection* edge survives cold markets; its *calibrated probability*
does not fully survive — it is regime-dependent.**

- **APPLY still beats the base rate in the cold slice — clearly.** Cold APPLY precision
  **83–84%** vs a cold base rate of **60–61%** (a **+23-point** edge, *larger* than in hot
  markets because the cold base rate is lower). Discrimination holds (cold AUC 0.76–0.79).
  So heavily-subscribed IPOs still tend to pop even in weak tapes — the *selection* is robust.
- **But calibration degrades in cold.** ECE rises to **0.10–0.13** in cold (vs 0.06–0.08
  hot) — over the 0.10 tolerance. The stated probability is less honest in weak markets.
- **And in the sharpest cold sub-period it appears to break.** H1 2022 (N=12): AUC 0.60,
  **ECE 0.41**, APPLY a coin-flip (1 of 2). A **red flag** — but the sample is far too thin
  (APPLY N=2) to be a verdict; read it as "calibration is fragile in a sharp correction,"
  not "the model is 50/50."
- **Caveats:** cold sub-samples are thin (wide CIs); even 2017–2026 has no multi-year bear
  (deepest stress = brief 2020 COVID + 2022 dip); the ~70% cold buckets are N=6–12.

## Recommendation — gate on regime, don't hide it

The model is currently **regime-blind**: `market_regime` was never populated, so it emits
the same confidence in a hot tape and a correcting one. The honest fix (your suggestion):

1. **Wire the Nifty `market_regime` feature in** (we now have the index series) and
   **re-run the Phase-4 calibration** with it.
2. If per-regime ECE does not converge, **calibrate per regime** (or **down-weight / gate
   APPLY when the regime is cold**) rather than showing an over-confident probability the
   cold data can't back up.
3. Keep stating sample size + base rate next to every probability, and **flag "cold market"**
   on the verdict so the operator sees the reduced reliability.

Bottom line, plainly: **trust the APPLY *selection* in cold markets; distrust the exact
*percentage* there until `market_regime` is wired in and the calibration re-passes per
regime.** Nothing here was tuned to improve the cold numbers.
