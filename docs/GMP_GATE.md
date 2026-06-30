# Phase-5 GMP Re-calibration Gate — real point-in-time GMP (IPOMatrix 2025-26)

*The first real test of THE Phase-5 question: does as-of-close GMP (level + slope) earn its weight in the calibrated model? Point-in-time (not leaky), our own net-of-open label, same IPOs scored with vs without GMP. Engineering/research reference — not financial advice.*

## Verdict: **NOT EARNED (provisional, hot-market only)**

> No significant marginal lift over the official QIB-led model: the AUC lift CI **includes zero in every split** and the keep/cut call **flips with the walk-forward window**. The burden of proof is on GMP to *demonstrate* it helps (Deep Dive #5); on this hot-market sample it does not, so **GMP stays out of the shipped model, provisionally** — revisit with cold-market point-in-time GMP from the recorder.

## Robustness across walk-forward splits (N is small — trust only what survives all)

| initial, step | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 60, 20 | 39 | keep | 0.770→0.778 | 0.184→0.164 | +0.008 [-0.058, +0.068] |
| 50, 15 | 49 | cut | 0.718→0.740 | 0.128→0.161 | +0.022 [-0.027, +0.070] |
| 40, 10 | 59 | cut | 0.741→0.755 | 0.169→0.186 | +0.014 [-0.021, +0.049] |

The AUC lift's CI **includes zero in every split**, and the ECE direction (and thus the keep/cut call) **flips** — i.e. GMP neither reliably discriminates better nor reliably calibrates better than the official QIB-led model on this data.

APPLY precision @ 0.65 (primary split 60/20): official-only 67% (N=18) vs +GMP 71% (N=17) — essentially unchanged.

## Why this matters vs the earlier leaky screen

The nikhilraj level-only screen (leaky, near-listing GMP) showed a large **+0.133** AUC lift (`GMP_SCREEN.md`). On **clean point-in-time** GMP that lift **collapses to ~0** — strong evidence the apparent GMP edge was mostly **leakage**, and that as-of-close GMP is largely **redundant with QIB** subscription in a hot market.

## Sample

- **136** mainboard IPOs matched to NSE with point-in-time GMP; **99** had sufficient as-of-close coverage and entered the gate.
- **1817** reconciled GMP day-points; GMP read strictly **as-of subscription close** (Allotted/Listed rows excluded by construction — not leaky).
- **Base rate (positive net listing):** 62% — a **hot market**.

## What this does NOT answer (boundaries — do not over-read)

- **Hot-market only.** Base rate ~62%; 2025-26 is one buoyant regime. Says nothing about GMP in cold markets, where QIB is weaker and GMP *might* carry more (or be more manipulated) — untestable without cold point-in-time GMP (cf. `REGIME_FIX.md`).
- **Single source** (IPOMatrix/Chittorgarh). Multi-source divergence/confidence flags and the spike-collapse kill-flag are **not** exercised here — this tests the *level+slope features*, not GMP's manipulation-detection role.
- **Small N / wide CIs.** ~40–60 OOS points. This is a real read, not the last word; re-run as the recorder banks more — and colder — point-in-time GMP.
