# PROJECT LOG — IPO Listing-Gains Advisor (permanent record)

*The single, consolidated record of **why the shipped model is shaped the way it is**: the build
history, every gate/probe result with its tables and confidence intervals verbatim, and the
disciplined negatives that kept features out. Assembled at project close (2026-07-05) by merging the
per-gate/per-feature evidence docs, the phase log (`PROGRESS.md`), and the v2 candidate ledger
(`V2_PROGRESS.md`). This file stays even though the project is closed.*

*Consolidation, not summary — the gate tables (splits, OOS N, `AUC off→on`, `ECE off→on`, AUC-lift
95% CIs), sample sizes, base rates, and verdicts are preserved as they were reported. Engineering /
research reference, **not financial advice**; the system is advisory-only (it places no orders).*

**Still-live governing documents (NOT merged here):** the two master blueprints
(`MASTER_BLUEPRINT_IPO_Listing_Advisor_Handoff.md`, `docs/v2/MASTER_BLUEPRINT_v2_Execution_and_Gate_Playbook.md`),
the deep dives (`docs/deep_dives/`, `docs/v2/deep_dives/`), and the operator rebuild guide
(`docs/GATE7_PACKAGING.md`).

---

## Table of contents

1. [The shipped model — what it is and why](#1-the-shipped-model)
2. [Phase history (P0–P7)](#2-phase-history-p0p7)
3. [v2 candidate ledger — promoted / rejected](#3-v2-candidate-ledger)
4. [Gate & probe evidence (verbatim)](#4-gate--probe-evidence)
   - [4.1 Calibration — the reliability gate (Phase 4, 358 IPOs)](#41-calibration)
   - [4.2 Benchmark — model vs subscription rules](#42-benchmark)
   - [4.3 GMP — the second sacred gate](#43-gmp)
   - [4.4 Enhancement gate — OFS / valuation / anchor](#44-enhancement-gate)
   - [4.5 Regime lineage — the cold-market flag](#45-regime-lineage)
   - [4.6 T+3 settlement cross-break stability](#46-t3-stability)
   - [4.7 v2 gates & probes — B1 / B2 / B3 / B6 / B7 / B8](#47-v2-gates)
   - [4.8 Shipped v2 features — A3 / B2-VIX / B9](#48-shipped-v2-features)
   - [4.9 Total-only / QIB-only — the category-split substitutability probe](#49-total-only)
5. [Shipped-app wiring — what's live](#5-shipped-app-wiring)

---

<a name="1-the-shipped-model"></a>
## 1. The shipped model — what it is and why

A calibrated, advisory-only listing-gains advisor for **Indian mainboard IPOs**. Point-in-time
subscription features → a fixed-weight scorer (the scorer owns signs; QIB/NII/anchor/regime add,
valuation/OFS brake) → a **Platt calibrator** that emits: a **verdict** (APPLY / MARGINAL / SKIP /
INSUFFICIENT_SIGNAL), a **calibrated probability shown only when the reliability gate passes**, and a
**grounded reason** citing real feature values ("QIB 200×, anchor 1.00"). Kill-flags (SME, collapsing
GMP, near-total OFS, promoter litigation) and abstention are separate from the score.

**The load-bearing design fact:** the model is **subscription-led (QIB)**, and nearly every
confirmation/brake feature tried turned out **QIB-redundant** — the settled QIB multiple already
encodes the signal. That thesis is not asserted; it is the *repeated result* of the gates below.

**The shipped calibrator** (`models/calibrator.json`):

- method **platt** · version `platt-1` · params `a=11.1668, b=-1.1172`
- `passes_reliability_gate: true`
- feature-code hash `d01815d61aec4d33` · label `net_of_cost(listing_open) > 0`
- **sample_size 358** · base_rate **0.697986577181208**

The calibrator is fit on the validated **358-IPO** dataset (2017–2026), and the recalibration ritual
reproduces it deterministically (max Δ 0.0). `critical_features = [qib_sub]`; `gmp_level` and
`market_regime` are **not** in the number (GMP is `None` by design; `market_regime` is a weight-0
annotation flag). Recalibrate quarterly and after regime shifts; a calibrated 70% still fails ~30% of
the time.

---

<a name="2-phase-history-p0p7"></a>
## 2. Phase history (P0–P7)

The committed tree is green (lint + types + tests) at every phase commit.

| Date | Phase | Status | Tests | Notes / decisions |
|---|---|---|---|---|
| 2026-06-29 | P0 Foundation | ☑ | 38 | Scaffolding, config/secrets, logging, NSE calendar, core contracts; GATE 0 met. |
| 2026-06-29 | P1 Ingestion + labels | ☑ | 78 | Official ingestion + listing-day labels; GATE 1 met. Tata Tech +140%, LIC −8.62% verified vs exchange. SME tagged/excluded. |
| 2026-06-29 | P2 Feature layer | ☑ | 105 | Leakage-free point-in-time feature vector; leakage suite passes/fails correctly; GATE 2 met. |
| 2026-06-29 | P3 Scoring core | ☑ | 132 | Scorer / kill-flags / verdict / grounded reason; GATE 3 met. Calibrator = marked placeholder; **no probability shown**. |
| 2026-06-29 | P4 Calibration | ☑ | 154 | **Reliability gate PASSED** on 311 official NSE IPOs (293 OOS-eligible). AUC 0.812, ECE 0.073, look-ahead 0.47. Platt default. `critical_features=[qib_sub]`. |
| 2026-06-29 | P4+ Benchmark | ☑ | 158 | Model **ties** the equal-selectivity QIB rule (83.7% vs 84.3%); the value is **calibration**, not precision. |
| 2026-06-30 | P5 GMP framework | ◐ | 168 | GMP machinery + re-calibration gate built & validated (keeps informative, rejects noise). Historical GMP deferred. |
| 2026-06-30 | P5+ GMP gate run | ◐ | 174 | Real gate RAN on 99 PIT 2025-26 IPOs (IPOMatrix trial). **GMP NOT earned** — clean as-of-close AUC lift ~0 (leaky +0.133 collapsed). Official-only ships. |
| 2026-07-03 | P5++ Enhancement gate | ◐ | 197 | **OFS / valuation / anchor gated (GMP-parity), all fail.** OFS **CUT**, valuation **NOT EARNED**, anchor **NOT TESTED**. Two blueprint-contradicting findings (§4.4). Dead-feature weights → 0.0 (byte-equality). Backfill/extraction quarantined to `research/`. |
| 2026-06-30 | P6 Advisory service | ☑ | 197 | **GATE 6 PASSED** — engine/API/scheduler/notify composed; all five invariants survive end-to-end. Cold flag LIVE; live GMP `None`. |
| 2026-07-03 | P7 The app | ☑ | 228 | **GATE 7 PASSED** — installs like real software, launches the bundled engine, shows **live** NSE verdicts, fires native APPLY notifications; all five invariants hold. NSIS `.exe` + Store MSIX. |
| 2026-07-04→05 | v2 | — | 269 | Dataset extension 293→358; A3/B2/B9/A4 shipped; B1/B2-score/B3/B6/B7/B8 gated-out or shelved (§3, §4). |

**Gate status:** 0 ☑ · 1 ☑ · 2 ☑ · 3 ☑ · 4 ☑ · 5 ☐ (GMP not earned; framework validated) · 6 ☑ · 7 ☑

### The two hard checkpoints (Deep Dives #4, #5)
- **Phase 4 — the reliability gate:** no probability is shown until the calibrator tracks
  predicted-vs-actual AND the look-ahead shuffle collapses skill to chance.
- **Phase 5 — the GMP re-calibration gate:** GMP stays in the model only if it measurably improves
  calibration; otherwise it is removed. (It was removed — §4.3.)

### Key locked decisions
- **A feature stays out of the number until calibration earns it.** `market_regime` weight 0
  (flag-only); `gmp_level` `None` live; disproven enhancement weights 0.0. All byte-equality proven.
- **Probability is gated on `passes_reliability_gate`** — until it passes, the verdict shows with an
  UNCALIBRATED banner and no number.
- **Net-of-cost label** (exit at listing-day open; STT/DP/exchange/GST). The model outputs a
  probability, not a rupee magnitude — History shows the *actual* net-of-cost outcome for listed IPOs.
- **Kaggle (skworld) used only as independent replication** — its gross-gain label never enters the
  calibrator (mixing label definitions is forbidden, Deep Dive #4).

### Standing decision — forward/recording jobs deferred (2026-07-03)
The operator runs no standing/daily recorders, so every v2 item needing **forward collection** is
**deferred, not rejected**: **A1** (day-wise subscription recorder — built then removed), **A2**
(always-on recorder — cancelled), **B1** (trajectory — needs A1's history), and the **GMP recorder** +
**B4** (GMP cold re-test) / **B5** (multi-source GMP confidence). Not affected: the app's in-session
`live.py` ingestion; A4 occasional rituals. Lift when the operator opts to run a recorder.

---

<a name="3-v2-candidate-ledger"></a>
## 3. v2 candidate ledger — promoted / rejected

*Every candidate ends in exactly one of two states: **PROMOTED** (gated, with a fitted weight and gate
evidence) or **REJECTED / NOT-SHIPPED** (a graveyard row). The default expected outcome of a gate
candidate is a logged negative — that is the discipline working, not a failure. Track A = BUILD items
(no gate). Track B = GATE items.*

| Date | Candidate | Track | Outcome | Detail |
|---|---|---|---|---|
| 2026-07-04 | **Dataset expansion 293→358** (extend to 2017) + 1 correction + recalibration | A (data) | **BUILT — gate RE-PASSED** *(tag `data-2017-extend`)* | +65 validated pre-2021 mainboard IPOs (2017–2020), two-source cross-checked (NSE vs Kaggle: QIB/NII/retail 98%, price+band 100%). Corrected Electronics Mart QIB 62.28→169.54 (3rd-source verified). Gate re-passed (AUC 0.797, ECE 0.081, APPLY-prec 0.848); recalibration reproduces (Δ0.0). No regression: flips 1 verdict of 386 (max Δprob 0.042); late ECE improved 0.056. OOS 233→298. Pre-2017 correctly rejected (single-source). |
| 2026-07-04 | **A3 — retail allotment odds** (P(allotment) only) | A | **BUILT** (display-only; no calibration impact) | `min(1, 1/retail_sub)` next to the verdict, separate code path. Proxy under-states actual ~1.7×; labelled an estimate, not tuned. §4.8. |
| 2026-07-04 | **B2 — India VIX flag-enrichment** (safe half) | B (annotation) | **BUILT** — weight 0, byte-equality proven | Blends India VIX into the cold flag (weight 0); OOS probabilities byte-identical. Add-only: 59→61 cold flags. §4.8. |
| 2026-07-04 | **B9 — graded regime tiers** (normal/soft/cold) | B (annotation) | **BUILT** — weight 0, byte-equality proven | Binary cold flag → tiers (soft −0.15 / cold −0.3). MAX \|Δprob\|=0.0. 239 normal / 13 soft / 59 cold. §4.8. |
| 2026-07-04 | **A4 — operate-phase hardening** (monitor · T+3 · housekeeping · heartbeat · recalibration check) | A | **BUILT** — GATE A4 met (3/3) | Five operator rituals; calibrator byte-for-byte untouched. §4.6, §5. |
| 2026-07-03 | **B3 — cheap adds:** NII split, issue size, pricing-vs-band, BRLM | B (gate) | **4 × NOT EARNED** — all shelved | Full gate per feature; all QIB-redundant. Structural finding: 292/293 price at band top. BRLM clean null validates leakage discipline. §4.7. |
| 2026-07-04 | **B6 — RHP mandated-disclosure extraction** → context (Option B) | B (probe) | **NOT VIABLE** — extractor dropped from `src/`, kept as evidence | Section detected 81%, structured litigation extracted 6/100 (~7% recall); OCR data ceiling. 0 fabricated (abstains rather than guesses). §4.7. |
| 2026-07-04 | **B2 (second half) — India VIX as a score feature** | B (gate) | **CUT — NOT EARNED** | AUC lift ≈0 (CI straddles zero every split); ECE worsens on all 3. QIB-redundant; bigger cold-inclusive 358 sample still earned no weight. §4.7. |
| 2026-07-04 | **B7 — model-architecture bake-off: TabPFN v2 vs the logistic core** | B (gate) | **LOGISTIC STAYS** — question closed | AUC edge +0.004/+0.009/+0.018 (every CI includes 0; none reaches +0.03 bar); ECE worse for TabPFN on all 3. Interpretability + opaque 29 MB/torch cost only raise the bar. §4.7. |
| 2026-07-04 | **B8 Idea 1 — conformal uncertainty bands** | B (built, not shipped) | **NOT PURSUED** — built + coverage-validated, chose not to ship *(tag `b8-conformal-shelved`)* | Rate-coverage 80%→80%, MAX \|Δprob\|=0.0. The cold flag already delivers the actionable message; bands were a refinement not worth the rework. Nothing reached main. §4.7. |
| 2026-07-05 | **B1 — subscription-trajectory cheap probe** (does the buildup SHAPE add signal?) | B (probe) | **PROBE-INCONCLUSIVE** — free-data route closed with evidence; NOT a permanent closure | HF/Chittorgarh finals faithful (98%) but day-wise truncates at day 2 (reaches verified final on 0.8%) → endpoint-reliable, path-useless. Salvage (N=120): NO PULSE, lift ≈0 all splits. A real B1 gate needs forward collection. §4.7. |
| 2026-06-30 | **GMP** — as-of-close level + slope | B (gate) | **NOT EARNED (provisional, hot-market only)** | AUC lift CI includes zero every split; keep/cut flips. Leaky +0.133 collapsed to ~0 on clean PIT. Revisit with cold-market PIT GMP from the recorder. §4.3. |
| 2026-07-03 | **OFS / relative valuation / anchor** (enhancement) | B (gate) | **CUT / NOT EARNED / NOT TESTED** | All QIB-redundant. **OFS kill-flag is backwards**; **valuation lift was an outlier artifact**. §4.4. |
| 2026-07-13→14 | **Total-only / QIB-only — category-split substitutability** (reduced-feature model) | B (gate) | **VALIDATED, HELD — sourcing decision pending** *(branch `total-only-gate`)* | Total-only statistically indistinguishable from shipped (AUC/ECE parity, passes reliability gate); survives regime+T+3 stress with one bounded caveat (cold ECE softer, known failure class); Upstox tested and conclusively closed as a source (endpoint-wide staleness, no in-API fix); NSE/BSE-direct licensing recommended — would unlock the full model, not just total-only. §4.9. |

---

<a name="4-gate--probe-evidence"></a>
## 4. Gate & probe evidence (verbatim)

*Shared methodology (GMP-parity): each candidate feature is scored **with vs without** on the same
IPOs, walk-forward out-of-sample, the **calibrator refit per arm** (a fixed prior weight, never a
fitted per-feature coefficient), reporting ECE + AUC and a paired-bootstrap CI on the AUC lift across
≥3 splits. The null hypothesis is **QIB-redundancy**; the burden of proof is on the feature. A cut is
declared when the AUC-lift CI includes zero and/or the keep/cut call flips with the window.*

<a name="41-calibration"></a>
### 4.1 Calibration — the reliability gate (Phase 4, 358 IPOs)

*The artifact that earns the right to show probabilities. Official-only (QIB-led) model.*

- Calibrator **platt** · feature-code hash `d01815d61aec4d33`
- Label `net_of_cost(listing_open) > 0` · **sample size (scored, OOS-eligible): 358** · base rate **69.8%**
- **OOS AUC 0.797 · ECE 0.081 · Brier 0.170** · APPLY precision @0.65 **84.8%** · look-ahead shuffled AUC **0.477** (must be ~0.5)

**Reliability gate: PASSED**

| Check | Result | Detail |
|---|---|---|
| discrimination | PASS | OOS AUC=0.797 (floor 0.55) |
| calibration | PASS | ECE=0.081 (bound 0.1) |
| beats_base_rate | PASS | APPLY precision=0.848 vs base rate 0.698 + 0.05 |
| time_stable | PASS | early ECE=0.136, late ECE=0.056 (bound 0.150) |
| look_ahead_collapses | PASS | shuffled-label AUC=0.477 (must be ~0.5) |
| abstention_excluded | PASS | INSUFFICIENT_SIGNAL cases excluded from scored metrics by construction |

**Reliability diagram (predicted vs observed, n=298 OOS):**

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

*(The original Phase-4 gate PASSED on the 311-IPO / 293-OOS official set at AUC 0.812 / ECE 0.073; the
358 figures above are the 2017-extension re-pass. ~358 mainboard IPOs is a small sample — per-bucket
CIs are wide; state sample size + base rate next to every probability.)*

<a name="42-benchmark"></a>
### 4.2 Benchmark — model vs subscription rules

*Same walk-forward OOS set (233 OOS at time of report), no tuning on the reported fold. APPLY
precision = fraction of selected IPOs that listed positive net-of-cost.*

| Method | N selected | APPLY precision | 95% CI | Losers | Avg loss (net) |
|---|---|---|---|---|---|
| Apply to all (base rate) | 233 | 69.1% | [62.9%, 74.7%] | 72 | -6.5% |
| Apply if overall subscription > 1x | 227 | 70.5% | [64.2%, 76.0%] | 67 | -6.8% |
| Apply if QIB > 1x | 233 | 69.1% | [62.9%, 74.7%] | 72 | -6.5% |
| Top-N by QIB (equal selectivity) | 153 | 84.3% | [77.7%, 89.2%] | 24 | -8.5% |
| Model APPLY verdicts | 153 | 83.7% | [77.0%, 88.7%] | 25 | -7.6% |

**The key head-to-head:** Model 83.7% (N=153, [77.0, 88.7]) vs Top-N-by-QIB 84.3% (N=153, [77.7,
89.2]) → gap **−0.7%, CIs overlap heavily — not a real edge.** Paired (where they disagree): model-only
1W/3L; QIB-rule-only 2W/2L. **The model's value is calibration** (an honest probability the yes/no
rules cannot emit), not selection precision.

**Calibration (233 OOS):**

| Bin predicted | Observed | N |
|---|---|---|
| 0.38 | 0.41 | 27 |
| 0.45 | 0.37 | 38 |
| 0.53 | 0.44 | 9 |
| 0.66 | 0.57 | 14 |
| 0.74 | 0.75 | 16 |
| 0.87 | 0.75 | 59 |
| 0.92 | 0.97 | 70 |

**Regime split (does the QIB rule break in a cold market?):**

| Year | N | Base rate | QIB>1x prec | Top-N-QIB prec | Model prec |
|---|---|---|---|---|---|
| 2022 | 14 | 57% | 57.1% | 80.0% | 80.0% |
| 2023 | 48 | 79% | 79.2% | 86.1% | 86.1% |
| 2024 | 70 | 74% | 74.3% | 83.0% | 83.0% |
| 2025 | 82 | 70% | 69.5% | 83.6% | 83.6% |
| 2026 | 19 | 32% | 31.6% | 75.0% | 75.0% |

Coldest slice = 2026 (base 32%): model 75.0% (N=4) vs top-N-QIB 75.0% (N=4). Kill-flags: of 193
heavily-oversubscribed (QIB>10×) IPOs, **0** tripped a flag — in the official-only dataset the flag
inputs (GMP slope, OFS) are not populated, so loss-avoidance value is demonstrable only once those land.

<a name="43-gmp"></a>
### 4.3 GMP — the second sacred gate

#### 4.3a Phase-5 re-calibration gate — real point-in-time GMP (IPOMatrix 2025-26) → NOT EARNED

*Does as-of-close GMP (level + slope) earn its weight? Point-in-time (not leaky), our net-of-open
label, same IPOs with vs without GMP.*

**Verdict: NOT EARNED (provisional, hot-market only).**

| initial, step | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 60, 20 | 39 | keep | 0.770→0.778 | 0.184→0.164 | +0.008 [-0.058, +0.068] |
| 50, 15 | 49 | cut | 0.718→0.740 | 0.128→0.161 | +0.022 [-0.027, +0.070] |
| 40, 10 | 59 | cut | 0.741→0.755 | 0.169→0.186 | +0.014 [-0.021, +0.049] |

The AUC-lift CI **includes zero in every split** and the ECE direction (thus keep/cut) **flips**.
APPLY precision @0.65 (60/20): official 67% (N=18) vs +GMP 71% (N=17) — essentially unchanged.
Sample: **136** matched to NSE; **99** had sufficient as-of-close coverage; **1817** reconciled GMP
day-points (Allotted/Listed rows excluded — not leaky); base rate **62%** (hot). Boundaries: hot-market
only, single-source (IPOMatrix/Chittorgarh), small N; the spike-collapse kill-flag is untested here.
Re-run when the recorder banks cold-regime PIT GMP.

#### 4.3b GMP level-only screen (nikhilraj Kaggle) — the leakage lesson

*Independent dataset, its own gross/open label, never fed to our calibrator. Tests one thing: does GMP
**level** add discrimination incremental to subscription?*

- Dataset **152** IPOs (2020–2023), **92** OOS.
- AUC total-subscription alone **0.749**; subscription + GMP level **0.882**; **marginal lift +0.133
  (95% paired-bootstrap CI [+0.062, +0.216]).**
- **But the single GMP value is almost certainly final/near-listing (LEAKY):** GMP-implied vs actual
  listing correlate ~0.92, 84% direction match — far tighter than as-of-close GMP (~70–75% directional).

**The lesson (referenced throughout):** on **clean point-in-time** GMP (4.3a) that **+0.133 collapses
to ~0** — strong evidence the apparent GMP edge was mostly **leakage**, and that as-of-close GMP is
largely redundant with QIB in a hot market. Verdict: INCONCLUSIVE — a leaky upper bound, not proof.

<a name="44-enhancement-gate"></a>
### 4.4 Enhancement gate — OFS / valuation / anchor

*Same burden of proof GMP got; gated **separately** per feature so a brittle field (valuation) can't
contaminate a clean one (OFS). Data = a one-time Chittorgarh research pull mapped to the 293
OOS-eligible official-NSE IPOs (name-verified, 0 false joins). All three stay out (GMP-parity).*

| Feature | Verdict | One line |
|---|---|---|
| **OFS** (`ofs_fraction`) | **CUT — not earned** | No AUC lift, calibration slightly *worse*; as a kill-flag the sign is **backwards**. |
| **Relative valuation** (`issue_pe ÷ peer_median_pe`) | **NOT EARNED** (CUT on hand-QA'd subset) | Apparent calibration benefit **evaporates** under strict peer-P/E QA; lift CI always includes zero. |
| **Anchor quality** (`anchor_quality`) | **NOT TESTED — data-limited** | Per-investor anchor book is API-rendered on Chittorgarh, not cleanly extractable. Deferred. |

#### ⚠️ Two findings that contradict the blueprint's assumptions

1. **The OFS kill-flag is BACKWARDS on our data.** The blueprint assumed high OFS (promoter exit) ⇒
   more listing losses. The opposite holds — high-OFS issues (large, established firms) list *better*:

   | OFS bucket | N | listing-loss rate (gross, vs band top) |
   |---|---|---|
   | OFS = 0 (pure fresh) | 34 | 26% |
   | 0 < OFS ≤ 0.5 | 103 | 30% |
   | 0.5 < OFS ≤ 0.9 | 86 | 23% |
   | **OFS > 0.9 (near-total)** | 70 | **17% (lowest)** |

   **A naive "OFS → SKIP" flag would hurt. Do not implement it.**

2. **Valuation's apparent lift was an outlier artifact.** On the loose 147 it *improved* ECE and
   "kept" on all splits; on the hand-QA'd trustworthy 93 it *worsened* ECE. **This is the concrete case
   for why data-QA *before* the gate is essential** — an outlier-dominated peer median manufactured a
   signal that evaporated once the junk was removed.

**OFS — CUT (N=293, base 70%)**, as the `−0.05 × ofs_fraction` brake, refit per arm:

| split (initial/step) | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 175/58 | 118 | cut | 0.815→0.820 | 0.071→0.086 | +0.005 [−0.020, +0.035] |
| 146/43 | 147 | cut | 0.829→0.828 | 0.066→0.074 | −0.001 [−0.022, +0.020] |
| 117/29 | 176 | cut | 0.817→0.818 | 0.085→0.092 | +0.001 [−0.017, +0.021] |

**Relative valuation — NOT EARNED (trustworthy N=93, base 66%)**, refit per arm:

| split (initial/step) | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 55/18 | 38 | cut | 0.858→0.878 | 0.119→0.142 | +0.020 [−0.000, +0.055] |
| 46/13 | 47 | cut | 0.875→0.876 | 0.119→0.124 | +0.002 [−0.040, +0.042] |
| 37/9 | 56 | cut | 0.900→0.893 | 0.116→0.142 | −0.007 [−0.044, +0.021] |

Valuation hand-QA: of 147 "clean", **93 trustworthy** after sanity bounds (peer P/E in [5,80] with ≥2
peers; issuer post-issue P/E in [3,120]); 28 single-peer, 18 issuer-P/E out-of-range, 8
all-peers-out-of-bounds dropped (e.g. Gandhar Oil relval 0.03, Zinka/BlackBuck loss-maker, Shadowfax
P/E 170). Anchor — NOT TESTED (per-investor book API-rendered; strong QIB-redundancy prior).

**Byte-for-byte confirmation** (weights zeroed in `config/default.yaml`, exactly as `market_regime`):
with all three features populated at weight 0, `MAX |Δscore| = 0.0` and `MAX |Δprob| = 0.0` vs the
shipped model. Backfill/extraction adapters quarantined to `research/` (excluded from build).

<a name="45-regime-lineage"></a>
### 4.5 Regime lineage — the cold-market flag

*Walk-forward OOS, full Phase-4 discipline, nothing tuned to flatter the cold numbers. Cold ≡ Nifty
negative 3-month trend or drawdown at listing.*

#### 4.5a Stress test — does the edge survive cold markets?

**Stage 1 — 2021+ sample (233 OOS):**

| Regime | N | Base | AUC | ECE | APPLY N | APPLY prec | 95% CI | ~70% obs/N |
|---|---|---|---|---|---|---|---|---|
| All | 233 | 69% | 0.81 | 0.073 | 153 | 84% | [77%, 89%] | 67% / 30 |
| Hot (Nifty up 3m) | 156 | 73% | 0.82 | 0.062 | 116 | 84% | [76%, 89%] | 61% / 18 |
| **Cold** | 77 | 61% | 0.79 | 0.131 | 37 | **84%** | [69%, 92%] | 75% / 12 |

**Stage 2 — extended to 2017 (298 OOS; adds 2018–19 bear + 2020 COVID; +75 IPOs 2017–2020):**

| Regime | N | Base | AUC | ECE | APPLY N | APPLY prec | 95% CI | ~70% obs/N |
|---|---|---|---|---|---|---|---|---|
| All | 298 | 70% | 0.80 | 0.081 | 191 | 85% | [79%, 89%] | 62% / 26 |
| Hot | 193 | 75% | 0.80 | 0.077 | 143 | 85% | [79%, 90%] | 57% / 14 |
| **Cold** | 105 | 60% | 0.76 | 0.102 | 48 | **83%** | [70%, 91%] | 83% / 6 |
| **Cold sub-period H1 2022** | 12 | 58% | **0.60** | **0.411** | 2 | **50%** | [9%, 91%] | — / 0 |

Data cross-check: official NSE QIB vs independent skworld Kaggle — **268 matched, QIB agrees within 5%
on 97% (261/268)**.

**Honest conclusion:** the model's **ranking/selection edge survives cold markets** (cold APPLY 83–84%
vs cold base 60–61%, a +23-pt edge; discrimination holds, cold AUC 0.76–0.79), **but its calibrated
probability is regime-dependent** (cold ECE 0.10–0.13, over the 0.10 tolerance). In the sharpest cold
sub-period (H1 2022, N=12) it appears to break (AUC 0.60, ECE 0.41) — too thin to be a verdict.

#### 4.5b Fix — wiring `market_regime` in, measured OOS

| Metric | Before (official-only) | After (regime-aware) |
|---|---|---|
| Cold ECE | 0.102 | **0.139** |
| Cold APPLY precision | 83% [70%,91%] (N=105, APPLY=48) | 87% [73%,94%] (N=105, APPLY=39) |
| Hot ECE | 0.077 | 0.072 |
| Hot APPLY precision | 85% [79%,90%] (N=193, APPLY=143) | 84% [77%,89%] (N=193, APPLY=145) |

Per-regime calibration (fallback): cold ECE **0.115** | cold APPLY 86% [73%,93%] (N=105, APPLY=43); 3
of 15 blocks fell back to pooled (cold fold < ~20). H1 2022: ECE 0.495, APPLY 100% [21%,100%] (N=12,
APPLY=1) — too thin. **Outcome: cold probability STILL does not calibrate → GATE/FLAG APPLY as
"cold-market — ranking reliable, probability less certain"; do not force the number.** The landed
design is **flag, don't force** (`market_regime` weight 0, threshold −0.3, an untuned prior).

**Positive finding on a larger cold sample:** independent skworld replication (546 OOS, 214 cold) found
**cold ECE 0.083 — within the 0.10 tolerance**, so in ordinary corrections the probability is more
honest than the ~105-cold sample suggested; the flag is, if anything, mildly conservative. **Known
limitation (unvalidated, NOT acted on by design):** deep cold / "IPO winter" (2011–13, skworld n=54,
12 APPLYs, AUC ≈0.50, gross label) — discrimination collapsed to chance. The system deliberately does
**not** auto-abstain in deep cold (that would be a second threshold fit to n≈1); operator judgement
applies in a prolonged primary-market freeze.

#### 4.5c Independent replication — skworld Kaggle (2010+, cold-richer)

*Own gross listing-gain label, never mixed into our calibrator. OOS 546 · cold 214 · hot 332 ·
deep-cold 2011–13 = 54.*

| Regime | N | Base | AUC | ECE | APPLY prec | 95% CI |
|---|---|---|---|---|---|---|
| All | 546 | 67% | 0.81 | 0.074 | 84% (N=331) | [79%, 87%] |
| Hot | 332 | 73% | 0.85 | 0.085 | 86% (N=234) | [81%, 90%] |
| Cold | 214 | 58% | 0.73 | 0.083 | 78% (N=97) | [69%, 85%] |
| Deep-cold 2011–2013 | 54 | 57% | 0.50 | 0.118 | 67% (N=12) | [39%, 86%] |

#### 4.5d Cold-flag threshold re-check (−0.3) — read-only

| threshold | all mainboard 2021+ | of which cold | known-cold (skworld) |
|---|---|---|---|
| -0.2 | 22% (N=293) | 68% (N=96) | 66% (N=234) |
| **-0.3 (current)** | **20% (N=293)** | **60% (N=96)** | **58% (N=234)** |
| -0.4 | 15% (N=293) | 45% (N=96) | 48% (N=234) |

At −0.3 the flag fires on 20% of all mainboard IPOs (a clear minority) and catches 58% of
independently known-cold IPOs — confirmed a reasonable prior, left unchanged. Never tune it to
listing outcomes (it is a prior on market state, not a fitted parameter).

<a name="46-t3-stability"></a>
### 4.6 T+3 settlement cross-break stability (A4)

*Does the calibrated model behave differently across the SEBI T+6→T+3 listing-timeline cutover
(mandatory **2023-12-01**)? Walk-forward OOS rows split by the `t3_regime` dummy. A **read-only
reported check** — the dummy is never added to the score and the calibrator is never refit.*

**Two results are recorded; they answer two different questions.**

**(1) The original T+3 question — STABLE (like-for-like 2021–2026 comparison, 233 OOS).** This is the
answer to *"did the settlement-cycle change (T+6→T+3) destabilize calibration?"* — matched pre/post
composition, and it **stands answered**:

| slice | n | base rate | APPLY precision @ 0.65 (95% CI) | ECE |
|---|---|---|---|---|
| pre-T+3 (< 2023-12-01) | 52 | 73% | 87% (95% CI 71%-95%, n=31) | 0.098 |
| post-T+3 (>= 2023-12-01) | 181 | 68% | 83% (95% CI 75%-88%, n=122) | 0.089 |

ECE shift across the break: **−0.009** (tolerance 0.030) → **STABLE.** No cross-break difference is
detectable at this sample size; the calibrator holds across the settlement cutover.

**(2) Regeneration on the full 358 sample — DIFFERENCE, but for a composition reason, not settlement.**
Re-running the check on the current 358-IPO data:

| slice | n | base rate | APPLY precision @ 0.65 (95% CI) | ECE |
|---|---|---|---|---|
| pre-T+3 (< 2023-12-01) | 117 | 73% | 87% (95% CI 77%-93%, n=70) | 0.134 |
| post-T+3 (>= 2023-12-01) | 181 | 68% | 83% (95% CI 76%-89%, n=121) | 0.075 |

ECE shift across the break: **−0.060** (tolerance 0.030) → **DIFFERENCE.**

**Why this is not a settlement-change regression.** The **post-cutover slice is identical in both runs
(n=181)**; only the **pre-cutover** slice changed — from n=52 to n=117. The +65 IPOs added by the
2017-extension are **all pre-2021 (2017–2020)** and therefore **all land in the pre-cutover bucket**,
and they are a **colder era** (2018–19 weakness, 2020 COVID). They raise the pre-cutover ECE from 0.098
to **0.134** — the same "cold IPOs calibrate worse" effect measured directly in §4.5, now showing up as
a pre-vs-post gap. In other words, the DIFFERENCE is driven by **cold-era composition in the
pre-cutover bucket**, not by the T+6→T+3 settlement change. The overall 358 calibrator still passes its
gate (ECE 0.081, §4.1). **Operator action** if a genuine settlement-driven difference ever emerges: a
recalibration on post-cutover data — not a silent change here.

<a name="47-v2-gates"></a>
### 4.7 v2 gates & probes — B1 / B2 / B3 / B6 / B7 / B8

#### B1 — subscription-trajectory cheap probe (does the buildup SHAPE add signal?) — INCONCLUSIVE

*Step-2 probe on probe-grade data (arXiv 2412.16174 / HF `sohomghosh/Indian_IPO_datasets`,
Chittorgarh day-wise). Read-only; nothing wired.*

**Trust-check (2017–2023 overlap, 121 matched IPOs):** the dataset's `Total_subscriptions` matches our
NSE-sourced finals on **98%** — **but the day-wise columns truncate at day 2** (their last recorded day
reaches our verified final on only **0.8%** of IPOs; the closing-day QIB surge is missing, e.g. Indigo
Paints our QIB 189.6× vs their last day 5.4×). **Endpoint-reliable, path-useless** → verdict **(c) data
too poor** for a clean probe.

**Salvage** (their day-2 cumulative QIB + our verified final → final-day QIB surge share, PIT at close,
N=120, base 69%): **NO PULSE.**

| split (initial/step) | OOS N | gate | AUC off->on | ECE off->on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 72/24 | 48 | cut | 0.794->0.782 | 0.138->0.160 | -0.012 [-0.044, +0.014] |
| 60/18 | 60 | cut | 0.759->0.751 | 0.163->0.172 | -0.007 [-0.037, +0.020] |
| 48/12 | 72 | cut | 0.752->0.753 | 0.165->0.177 | +0.001 [-0.019, +0.021] |

Consistent with the QIB-redundant prior, but on probe-grade-squared data it does **not** permanently
close B1. A real B1 gate requires forward collection (recorder); no cheap positive signal exists to chase.

#### B2 (second half) — India VIX as a score feature — CUT

*The flag-enrichment half shipped weight-0 (§4.8); this gates the score-feature half on the 358 sample.*

- Clean-coverage N **358** · base rate 68% · APPLY precision @0.65: off 85% (N=89) vs on 86% (N=90)

| split (initial/step) | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 214/71 | 144 | cut | 0.827→0.823 | 0.055→0.058 | -0.005 [-0.025, +0.018] |
| 179/53 | 179 | cut | 0.826→0.826 | 0.060→0.074 | +0.000 [-0.016, +0.019] |
| 143/35 | 215 | cut | 0.834→0.832 | 0.060→0.068 | -0.002 [-0.017, +0.012] |

AUC lift ≈0 (CI straddles zero on every split) and ECE **worsens on all 3** → QIB-redundant (fear
already echoes through cautious QIB bidding). The cold-market-inclusive 358 sample gave it a fairer
shot and it still earned no weight.

#### B3 — cheap adds: NII split / issue size / pricing-vs-band / BRLM — 4 × NOT EARNED

| feature | N | verdict | one line |
|---|---|---|---|
| NII split (sNII/bNII) | 235 | **NOT EARNED** | negative/flat lift, CI straddles zero, keep/cut flips — QIB-redundant |
| Bucketed issue size | 293 | **NOT EARNED** | positive but small; CI includes zero on 2/3 splits and flips — least-unpromising, still not earned |
| Pricing-vs-band | 293 | **NOT EARNED** *(structural)* | **292/293 priced at the band top** — feature near-constant |
| BRLM reputation | 292 | **NOT EARNED** | AUC lift is noise (CI straddles zero); ECE improved but discrimination didn't; leakage-safe → no fake lift |

**Two findings worth more than the features would have been:**
1. **Pricing-vs-band is a permanent structural fact.** 292 of 293 mainboard IPOs priced their cut-off
   exactly at the band top (1 below). The "voluntary underpricing via cut-off" channel **does not exist**
   for Indian mainboard book-builds — closing off an entire category of feature ideas. Do not chase
   cut-off-pricing features again.
2. **BRLM's clean null validates the leakage discipline.** BRLM was the feature *most* at risk of a
   leakage artifact (a naïve full-period league table leaks the future). Built **point-in-time** (each
   manager's share among only *earlier* IPOs), it produced **no fake lift** — contrast GMP's leaked
   +0.133. When the construction is honest, a redundant feature correctly shows ~zero. **These negatives
   are trustworthy real nulls, not artifacts hiding a signal.**

NII split (N=235, base 70%; off 81% N=54 vs on 82% N=55):

| split (initial/step) | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 141/47 | 94 | cut | 0.795→0.791 | 0.071→0.094 | -0.004 [-0.027, +0.021] |
| 117/35 | 118 | keep | 0.820→0.812 | 0.079→0.053 | -0.008 [-0.025, +0.009] |
| 94/23 | 141 | cut | 0.816→0.806 | 0.063→0.084 | -0.010 [-0.023, +0.003] |

Bucketed issue size (N=293, base 70%; off 86% N=70 vs on 87% N=69):

| split (initial/step) | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 175/58 | 118 | cut | 0.815→0.825 | 0.071→0.072 | +0.010 [-0.010, +0.030] |
| 146/43 | 147 | keep | 0.829→0.837 | 0.066→0.055 | +0.008 [-0.006, +0.023] |
| 117/29 | 176 | keep | 0.817→0.830 | 0.085→0.078 | +0.013 [+0.001, +0.026] |

Pricing-vs-band (cut-off ÷ band top, N=293, base 70%; off 86% vs on 86%):

| split (initial/step) | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 175/58 | 118 | keep | 0.815→0.815 | 0.071→0.071 | +0.000 [+0.000, +0.002] |
| 146/43 | 147 | keep | 0.829→0.829 | 0.066→0.057 | +0.000 [-0.002, +0.002] |
| 117/29 | 176 | keep | 0.817→0.817 | 0.085→0.081 | +0.000 [-0.001, +0.002] |

BRLM reputation (point-in-time league share, N=292, base 70%; off 86% N=70 vs on 88% N=68):

| split (initial/step) | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 175/58 | 117 | keep | 0.815→0.811 | 0.087→0.068 | -0.003 [-0.025, +0.018] |
| 146/43 | 146 | keep | 0.826→0.821 | 0.078→0.048 | -0.005 [-0.023, +0.011] |
| 116/29 | 176 | keep | 0.818→0.817 | 0.095→0.075 | -0.001 [-0.015, +0.012] |

#### B6 — RHP mandated-disclosure extraction probe — NOT VIABLE

*Option B (informational context only, no scoring). Probe-before-build over 100 real OCR'd Indian IPO
prospectuses (`scholarly360/indian_ipo_prospectus_data`). The extractor was never wired; it was removed
from `src/` and quarantined in `research/`.*

| Signal | Result | Usable to display? |
|---|---|---|
| Litigation **section detected** | **81 / 100 (81%)** | Partial — a coarse "section present" flag only |
| Structured **litigation count/amount** (vs the Company) | **6 / 100 (6%)** extracted; **0 fabricated** — Vedant 22/₹240.53mn, Delhivery 89/₹411.69mn exact | **No** — ~7% recall |
| **Auditor opinion** | 54 / 100 (emphasis-of-matter 46, qualified 5, unqualified 3) | Maybe — a coarse flag |
| **Related-party disclosed** | **100 / 100 (constant)** | No — zero discrimination |

Root cause is a **data ceiling** — OCR-reflowed mandated tables (column headers bleed into rows, `N.A.`
spellings vary, footnote markers corrupt tokens), not a fixable regex. **Precision is high by
construction** (the parser requires ≥4 of 5 mandated columns and **abstains rather than guesses** — it
validates the never-invent safeguard). Recommendation: coarse auditor-opinion flag only, or drop B6.

#### B7 — TabPFN v2 vs the logistic core — LOGISTIC STAYS

*Head-to-head on 358, same walk-forward folds, same core features (QIB/NII/retail). **Higher bar:**
adopting TabPFN forfeits the grounded reason, so it must win **decisively** (AUC lift ≥0.03, CI clear of
zero every split, ECE no worse) — not on a tie.*

| split (initial/step) | OOS N | AUC logistic | AUC TabPFN | ECE logistic | ECE TabPFN | AUC diff (95% CI) |
|---|---|---|---|---|---|---|
| 214/71 | 144 | 0.827 | 0.831 | 0.055 | 0.103 | +0.004 [-0.034, +0.040] |
| 179/53 | 179 | 0.826 | 0.834 | 0.060 | 0.093 | +0.009 [-0.023, +0.040] |
| 143/35 | 215 | 0.834 | 0.852 | 0.060 | 0.080 | +0.018 [-0.008, +0.043] |

Largest edge +0.018 (short of the 0.03 bar); every CI includes zero; **ECE worse for TabPFN on every
split** — costly for a calibrated-probability product. Adopting TabPFN would add an opaque ~29 MB
transformer (torch, ~500 MB installed) with vendor telemetry and a license-gating trajectory — raising,
not lowering, the bar. Deterministic (`random_state=0`, bootstrap `seed=17`). **Interpretability
outweighs any marginal metric edge — logistic retained, question closed.**

#### B8 Idea 1 — conformal uncertainty bands — SHELVED (built + validated, not shipped)

*A narrow, symmetric range around the calibrated point estimate that widens in unfamiliar/cold markets
— the epistemic uncertainty in the **rate estimate**, the quantitative companion to the cold flag.
Distribution-free normalized split-conformal at the rate level. Preserved off-main under git tag
`b8-conformal-shelved`.*

- **Gate 1 — no scoring impact:** two live engines over the whole backfill, bands wired vs not → every
  probability and verdict **byte-for-byte identical (MAX |Δprob| = 0.0)** while the wired engine attaches
  bands. The band is computed downstream of `verdict.probability`.
- **Gate 2 — the bands are honest** (held-out rate-coverage, N=298 OOS):

  | Claimed | Realized (band contains the true local rate) | Mean width |
  |---|---|---|
  | **80%** | **80%** | 0.33 |

- **Behavior** (APPLY mean width warm ±0.08, cold ±0.12): Crizac (93%, warm) `[83,100]` vs Senores
  (94%, cold) `[74,100]` — *same confidence, cold → wider*; Aether (60%, cold) `[10,100]` — uncertain and
  cold → very wide. Widens in cold at matched confidence; narrow + symmetric where it matters.

**Why not shipped:** the cold flag (B9/B2) already delivers the actionable message ("be more cautious in
unfamiliar markets"); the bands were a quantitative refinement not worth the core-module rework.
Nothing reached main. *(A fork is recorded: an **outcome-coverage** band was built first but forces
asymmetric wide floors — 83%→[42,100] — that read as a worst-case bound; the **rate-estimate** band is
the correct object for "how much to trust this number", validated by rate-coverage. The outcome-band
version was discarded, not merged.)*

<a name="48-shipped-v2-features"></a>
### 4.8 Shipped v2 features — A3 / B2-VIX / B9

*All three are display/annotation refinements that provably do not touch the number. Byte-equality
proven; the shipped calibrator is untouched.*

#### A3 — retail allotment odds (P(allotment) only)

`src/ipo/service/allotment.py::retail_allotment_odds(retail_sub) = min(1, 1/retail_sub)`, a **separate
downstream display-only** estimate wired through `engine.detail()` → `IPODetail.retail_allotment_odds`
→ `/ipo/{id}` → `Detail.tsx`. It never touches the scorer/calibrator (separate code path). Scoped down
from the full EV layer (gain-magnitude + opportunity-cost dropped — the model deliberately produces no
magnitude, and ~₹8 ASBA cost is negligible).

**Honest back-check** (actual published retail lottery ratios, not the circular `1/subscription`):

| IPO | retail_sub | proxy `1/retail_sub` | **actual** allotment | actual ÷ proxy (k) | gap |
|---|---|---|---|---|---|
| Tata Technologies (2023) | 16.5× | 6.1% | **12.0%** (10 of 83) | 1.99 | +6.0 pp |
| Bajaj Housing Finance (2024) | 7.04× | 14.2% | **20.0%** (≈1 in 5) | 1.41 | +5.8 pp |
| | | | | **mean k ≈ 1.70** | |

The proxy **under-states** actual by ~1.4–2.0× (mean ≈1.7×) — consistent with `k/retail_sub` (retail
applicants average ~1.7 lots). Directionally right; **not tuned** (per operator instruction — two points
don't justify a fudge factor). Shipped as a conservative **floor**, framed "**≥ ~X%**", visually
distinct from the calibrated probability.

#### B2 — India VIX flag-enrichment (safe half)

Blends India VIX into the cold-market flag at **weight 0**. `vix.csv` — 4490 rows, 2008-03-03 →
2026-07-03 (Yahoo `^INDIAVIX`), one-time backfill, bundled alongside `nifty.csv`. `VixSeries.vol_stress_at`
+ the engine `_market_regime_at` blend are **add-only** (stress floored at 0): elevated VIX only
*tightens* the flag, calm VIX **never lifts** a caveat the trend alone raised. Byte-equality proven
(`test_vix_flag_wiring`: OOS probabilities byte-for-byte identical, non-vacuous — VIX flips ≥1 flag).

| | cold-flagged |
|---|---|
| trend-only (before) | 59 |
| trend + VIX (after) | **61** |

VIX **added** the caveat to 2 IPOs (Anand Rathi, Adani Wilmar — both closed during volatility spikes)
and **removed it from none**.

#### B9 — graded regime tiers (normal / soft / cold)

Binary cold flag → `model/verdict.py::regime_tier`: **normal** (`> soft`, no caveat), **soft**
(`cold < r ≤ soft`, "softening market — probability a touch less certain"), **cold** (`≤ cold`,
"cold market — probability less certain", unchanged). Boundaries `soft_regime_flag = −0.15` (new) and
`cold_regime_flag = −0.3` (existing) — untuned a-priori round numbers. Computed **after** the
probability (weight 0). Byte-equality proven (`test_regime_tiers_wiring`: same verdict type,
**MAX |Δprob| = 0.0**, both tiers non-vacuously populated).

| tier | count (311 backfill) | caveat |
|---|---|---|
| normal | 239 | none |
| **soft** | **13** | "softening market — … a touch less certain" (**new**) |
| cold | 59 | "cold market — … less certain" (unchanged) |

<a name="49-total-only"></a>
### 4.9 Total-only / QIB-only — the category-split substitutability probe

*Off-main branch `total-only-gate` (2026-07-13→14), consolidated here as a closed finding — model and
data untouched, calibrator byte-identical throughout. Full backing: `research/TOTAL_ONLY_GATE.md`,
`research/CHECK1_FIELD_VERIFICATION.md`, `research/CHECK2_REGIME_T3_STABILITY.md`,
`research/CHECK3_DEPLOYABILITY_VERDICT.md`.*

The shipped model's QIB/NII/Retail split is not licensable from most real public feeds (brokers
typically expose only a single Total oversubscription multiple). Does a model built on **Total-only**
(no split at all) come close to the shipped model, survive the same stress tests, and does a real
source exist that measures it correctly? QIB-only runs as the intermediate rung (QIB dominates the
full model's contribution), so any dropoff shows in steps: full → QIB-only → Total-only.

**Gate parity** (same 358-IPO set, same walk-forward, calibrator refit per arm — GMP-parity
discipline):

| arm | OOS N | AUC | ECE | APPLY@0.65 precision |
|---|---|---|---|---|
| full (shipped) | 298 | 0.797 | 0.081 | 84.8% [79.0%, 89.2%] |
| qib_only | 298 | 0.805 | 0.084 | 85.3% [79.6%, 89.7%] |
| total_only | 298 | 0.805 | 0.079 | 85.1% [79.2%, 89.5%] |

Per-split AUC-lift 95% CIs include zero on every split for both reduced arms (max Δ +0.007); **all
three arms pass the identical six-check reliability gate**. Mechanism: total is a 0.93-Spearman
rank-copy of QIB, and the total-only score tracks the *full model's* ranking at 0.979 — tighter than
QIB-only (0.929) — because total saturates less against the winsorization cap (3 vs 19 of 358 IPOs).

**Regime + T+3 stress-test** (identical shipped functions; the full-model control reproduced the
§4.5/§4.6 numbers exactly, validating the harness before trusting the new ones): total-only's ranking
edge holds or improves in every regime (AUC 0.81/0.81/0.77 vs full's 0.80/0.80/0.76 for All/Hot/Cold),
and cold APPLY precision is statistically unchanged (83% vs 83%, overlapping CIs). **The one real
finding:** cold-regime ECE is softer — 0.133 vs full's already-marginal 0.102 — the same "cold markets
calibrate worse" failure class the shipped model already manages via its weight-0 regime flag, not a
new one, at a somewhat larger magnitude. T+3 cross-break shift (−0.062 vs full's −0.060) matches
full's for the identical already-documented composition reason (not a settlement effect).

**Sourcing** — Upstox (Analytics-Token developer API) tested as the concrete licensed-feed candidate
and **conclusively closed**: its `total_subscription` matches our NSE-sourced definition when the
value is final (118 IPOs matched, recent-window median gap 0.57%), but 30% of matches disagree by
>10% (stale pre-close snapshots), the details endpoint (`/v2/ipos/{id}`) serves the byte-identical
stale value as the list endpoint (no in-API fix), and the failure persists even for IPOs closing after
the API's own 2026-05-23 launch (2/10 tested, one in a new too-high direction) — ruling out both an
adjustment factor and a "wait for fresher data" fix. Our own backfill was independently confirmed
clean (14/14 exact match against a live cache-bypassed NSE re-fetch). Upstox's **consumer website**
(not the API) does show the full day-wise QIB/NII/Retail split, confirming the split's authoritative
home is **NSE/BSE** — reframing the recommendation: NSE/BSE-direct licensing would unlock the *full*
model, not just total-only.

**Verdict: VALIDATED, HELD — not shipped, sourcing decision pending.** Total-only clears every bar
the shipped model clears (gate parity, reliability gate, regime and T+3 robustness) with one bounded,
already-understood caveat (softer cold-market calibration, manageable with the existing
flag-don't-force mechanism applied a notch more conservatively). What remains unresolved is sourcing,
not modeling: Upstox is closed on data-quality grounds; NSE/BSE-direct licensing is the standing
recommendation, carried into the legal/vendor conversation. No further work without an explicit
decision to reopen it.

---

<a name="5-shipped-app-wiring"></a>
## 5. Shipped-app wiring — what's live

The packaged Windows app (NSIS `.exe` + MSIX) = an Electron shell + a PyInstaller'd FastAPI engine
sidecar + a React/PWA front end. As of the live-ingestion cutover (2026-07-03) it is genuinely live.

**Wired and working:**
- **Sidecar lifecycle** — Electron spawns the engine on a free port, health-gates `/health`, tears it
  down on every exit path (no orphaned Python); tray, remembered window state, startup toggles, splash.
- **The scoring engine** — features → scorer → kill-flags → verdict → grounded reason → calibrated
  probability, reliability-gated, using the committed **358-IPO** Platt calibrator (`models/calibrator.json`).
- **Live NSE ingestion** — `data/ingest/live.py::refresh_from_nse` (current issues → per-category
  subscription incl. sNII/bNII → `IPORecord`s → store), wired as the scheduler `refresh` in
  `runner.main()`. Never raises — a data hiccup degrades to the last store. Live-only build: **no demo
  seed ships**; a fresh install fills purely from live NSE ingestion (stale data self-heals on update).
  *[Superseded post-close (v3, 2026-07-16): the shipped app is now **VM-primary** — it reads records/
  context from the VM read-API first and uses this local NSE scrape as the honest fallback. This
  section is the 2026-07-05 close snapshot and is left as-is; see `operations/README.md` for the
  current data-plane wiring.]*
- **Read-only API + UI** — the UI reads engine output verbatim (all five invariants hold); cost
  overrides recompute net-of-cost History; verdict-transition log + alert center render; A3 allotment
  odds + graded cold caveats render on Detail.
- **Native notifications** on new APPLY crossings (renderer toasts, first-run silent, quiet-hours
  defer); **settings persist** across restart (window bounds + startup prefs + UI/notification prefs) in
  the per-user `settings.json`.
- **A4 operator rituals** (occasional, not daemons): drift monitor, T+3 stability, heartbeat,
  recalibration-reproduces check — all run against the current repo state.

**Out by design (not gaps):**
- **GMP is out** — it failed its own gate (§4.3); `features/gmp.py` is unused at runtime (the framework
  is retained + tested for a future cold-market re-run). The UI states "GMP is not a scoring input."
- **Enhancement features have no live feed** — anchor/valuation/OFS come from the RHP/prospectus; no
  adapter parses them live (deliberately "too brittle to ship"). The engine still scores (`qib_sub` is
  the only critical feature) and their weights are 0 anyway (§4.4).
- **Public-distribution caveat** — the app pulls live NSE from the user's machine (`respect_robots=False`
  for `/api`, operator-authorized public data). Wide public distribution would prefer a hosted API.
- **Auto-update deferred** (the Store delivers updates); MSIX re-signed free on submission.

*Build/rebuild instructions (how to freeze the engine + build the installer, signing, the Windows-11
makeappx workaround) live in the still-current operator guide `docs/GATE7_PACKAGING.md`.*
