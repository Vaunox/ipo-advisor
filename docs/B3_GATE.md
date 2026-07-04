# B3 cheap-adds re-calibration gate — NII split / bucketed issue size

*Each feature scored WITH vs WITHOUT on the same IPOs, walk-forward OOS, **calibrator refit per arm** (GMP-parity — fixed prior weight, not a fitted coefficient), ECE + AUC + a paired-bootstrap CI on the AUC lift across ≥3 splits. The null hypothesis is **QIB-redundancy**; the burden of proof is on the feature. Data recovered from the cached NSE raws (NII split), the Chittorgarh pull (issue size, BRLM, final price). Engineering/research reference — not financial advice.*

## Verdict: four features, four honest negatives

| feature | N | verdict | one line |
|---|---|---|---|
| NII split (sNII/bNII) | 235 | **NOT EARNED** | negative/flat lift, CI straddles zero, keep/cut flips — QIB-redundant |
| Bucketed issue size | 293 | **NOT EARNED** | positive but small; CI includes zero on 2/3 splits and flips — the least-unpromising, still not earned |
| Pricing-vs-band | 293 | **NOT EARNED** *(structural)* | **292/293 priced at the band top** — the feature is near-constant; see finding #1 |
| BRLM reputation | 292 | **NOT EARNED** | AUC lift is noise (CI straddles zero); **ECE improved but discrimination didn't**; leakage-safe → no fake lift (finding #2) |

All four stay out. **No `src/` change; the shipped calibrator is byte-for-byte untouched.** A *successful* B3 — four "shouldn't we try…?" questions converted into four settled "tested, no" answers with evidence, so they are never re-litigated.

## Two findings worth more than the features would have been

**1. Pricing-vs-band is a permanent structural fact about the market, not just a null.** Of 293 mainboard IPOs, **292 priced their cut-off exactly at the band top** (1 below). The "voluntary underpricing via cut-off" channel this feature assumes **does not exist for Indian mainboard book-builds** — they price at the top by construction, so the feature is ~constant (lift +0.000 every split). This closes off an **entire category** of feature ideas premised on cut-off-pricing dynamics, not merely this one. **Do not chase cut-off-pricing features again** unless there is new evidence the pricing behaviour has changed.

**2. BRLM's clean null validates the leakage discipline.** BRLM reputation was the feature *most* at risk of smuggling in a leakage artifact (a naïve full-period league table leaks the future into the past). It was built **point-in-time** — each manager's market share among only *earlier* IPOs — and it produced **no fake lift** (AUC lift indistinguishable from zero every split). Contrast **GMP's original +0.133**, which turned out to be pure leakage. The lesson: when the construction is honest, a redundant feature correctly shows **~zero**, not a fake lift that fools you — so these negatives are **trustworthy real nulls**, not artifacts hiding a signal. *(BRLM's ECE improved 0.087→0.068, but calibration-improving-alone is not a pass: the rule is improve one metric and worsen neither, with a CI that isn't noise. Here the discrimination lift CI straddles zero → not earned. The ECE move must not be misread as a missed promotion.)*

---

## NII split (sNII + bNII) — **NOT EARNED**

> No significant lift: the AUC-lift CI includes zero and/or the keep/cut call flips with the walk-forward window. On this sample NII split (sNII + bNII) does not demonstrably help — stays out.

- Clean-coverage N: **235** · base rate 70% · APPLY precision @ 0.65: off 81% (N=54) vs on 82% (N=55)

| split (initial/step) | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 141/47 | 94 | cut | 0.795→0.791 | 0.071→0.094 | -0.004 [-0.027, +0.021] |
| 117/35 | 118 | keep | 0.820→0.812 | 0.079→0.053 | -0.008 [-0.025, +0.009] |
| 94/23 | 141 | cut | 0.816→0.806 | 0.063→0.084 | -0.010 [-0.023, +0.003] |

## Bucketed issue size — **NOT EARNED**

> No significant lift: the AUC-lift CI includes zero and/or the keep/cut call flips with the walk-forward window. On this sample Bucketed issue size does not demonstrably help — stays out.

- Clean-coverage N: **293** · base rate 70% · APPLY precision @ 0.65: off 86% (N=70) vs on 87% (N=69)

| split (initial/step) | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 175/58 | 118 | cut | 0.815→0.825 | 0.071→0.072 | +0.010 [-0.010, +0.030] |
| 146/43 | 147 | keep | 0.829→0.837 | 0.066→0.055 | +0.008 [-0.006, +0.023] |
| 117/29 | 176 | keep | 0.817→0.830 | 0.085→0.078 | +0.013 [+0.001, +0.026] |

---

## Deferred features — sourced from the Chittorgarh pages and gated

*Both were first deferred as data-limited; the data was then recovered. Pricing-vs-band: final price ÷ band top on **293** IPOs — **1** priced below the top (mainboard book-builds price at the cut-off = band top, so near-constant). BRLM reputation: a **point-in-time** league table (each manager's market share among IPOs that closed earlier), on **292** IPOs — leakage-safe by construction.*

### Pricing-vs-band (cut-off ÷ band top) — **NOT EARNED**

> No significant lift: the AUC-lift CI includes zero and/or the keep/cut call flips with the walk-forward window. On this sample Pricing-vs-band (cut-off ÷ band top) does not demonstrably help — stays out.

- Clean-coverage N: **293** · base rate 70% · APPLY precision @ 0.65: off 86% (N=70) vs on 86% (N=70)

| split (initial/step) | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 175/58 | 118 | keep | 0.815→0.815 | 0.071→0.071 | +0.000 [+0.000, +0.002] |
| 146/43 | 147 | keep | 0.829→0.829 | 0.066→0.057 | +0.000 [-0.002, +0.002] |
| 117/29 | 176 | keep | 0.817→0.817 | 0.085→0.081 | +0.000 [-0.001, +0.002] |

### BRLM reputation (point-in-time league share) — **NOT EARNED**

> No significant lift: the AUC-lift CI includes zero and/or the keep/cut call flips with the walk-forward window. On this sample BRLM reputation (point-in-time league share) does not demonstrably help — stays out.

- Clean-coverage N: **292** · base rate 70% · APPLY precision @ 0.65: off 86% (N=70) vs on 88% (N=68)

| split (initial/step) | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 175/58 | 117 | keep | 0.815→0.811 | 0.087→0.068 | -0.003 [-0.025, +0.018] |
| 146/43 | 146 | keep | 0.826→0.821 | 0.078→0.048 | -0.005 [-0.023, +0.011] |
| 116/29 | 176 | keep | 0.818→0.817 | 0.095→0.075 | -0.001 [-0.015, +0.012] |
