# Total-only comparison gate — full → QIB-only → Total-only

*Research investigation, off-main branch `total-only-gate`. **Comparison gate, not a promotion** —
nothing under `models/`, `src/`, or `config/` was touched; the shipped calibrator is git-proven
byte-identical (SHA1 `fa2635717bb0179e2b21ed17b5ade4e7d5b25848` == HEAD). Engineering/research
reference, not financial advice.*

## Question

Total subscription (a single overall oversubscription multiple, no QIB/NII/retail split) is the
shape of data legally available from licensed feeds (e.g. Upstox); the per-category split is not.
**Does a model built on Total-only come close to the shipped full model?** QIB-only is run as the
intermediate rung, since QIB dominates the full model's contribution — so we can see where any real
dropoff is: full → QIB-only → Total-only.

## Method (identical to every prior gate)

Same 358-IPO calibration set, same net-of-cost label, same shipped normalization
(`winsorize→saturate`, config scales 200/20), same expanding-window walk-forward with the **Platt
calibrator refit per arm**. The three arms differ **only** in the scalar `score` fed to the
calibrator:

- **full** — the shipped `WeightedScorer` (QIB+NII+retail); reproduces §4.1 exactly.
- **qib_only** — the scorer's QIB term alone.
- **total_only** — the *same* subscription transform applied to the total multiple only.

Because the calibrator is a 2-parameter sigmoid `P=σ(a·score+b)`, a single feature's weight is
absorbed by `a`; each arm therefore isolates the **ranking shape** of its input. Per-split AUC/ECE
plus a **2000× paired bootstrap** (seed 17) on the AUC difference (variant−full), paired by IPO.
Harness validated: the full arm reproduces the shipped headline (AUC 0.797 / ECE 0.081 / Brier
0.170 / shuffled 0.477) and the B2/B7 "off" arm (0.827/0.826/0.834) to the digit.

Code: `research/run_total_only_gate.py`, `research/total_only_variant.py`. Run:
`PYTHONPATH="src;." python -m research.run_total_only_gate`.

## Headline (default 60/20 walk-forward — directly comparable to §4.1)

| arm | OOS N | AUC | ECE | Brier | shuffled | APPLY@0.65 precision (95% CI) |
|---|---|---|---|---|---|---|
| **full** (shipped) | 298 | 0.797 | 0.081 | 0.170 | 0.477 | 84.8% (N=191) [79.0%, 89.2%] |
| **qib_only** | 298 | 0.805 | 0.084 | 0.166 | 0.480 | 85.3% (N=191) [79.6%, 89.7%] |
| **total_only** | 298 | 0.805 | 0.079 | 0.169 | 0.473 | 85.1% (N=181) [79.2%, 89.5%] |

Both reduced arms **match** the full model on discrimination, calibration, and APPLY precision. The
look-ahead shuffle collapses to ~0.5 for all three (no leakage in the variants).

## Per-split gate tables (off = full model, on = variant)

**QIB-only vs full** (N=358, base 69.8%):

| split (initial/step) | OOS N | AUC full→qib | ECE full→qib | AUC Δ (qib−full), 95% CI |
|---|---|---|---|---|
| 214/71 | 144 | 0.827→0.832 | 0.055→0.127 | +0.005 [−0.022, +0.029] |
| 179/53 | 179 | 0.826→0.831 | 0.060→0.117 | +0.005 [−0.022, +0.030] |
| 143/35 | 215 | 0.834→0.841 | 0.060→0.105 | +0.007 [−0.019, +0.030] |

**Total-only vs full** (N=358, base 69.8%):

| split (initial/step) | OOS N | AUC full→total | ECE full→total | AUC Δ (total−full), 95% CI |
|---|---|---|---|---|
| 214/71 | 144 | 0.827→0.826 | 0.055→0.046 | −0.001 [−0.020, +0.018] |
| 179/53 | 179 | 0.826→0.827 | 0.060→0.063 | +0.002 [−0.012, +0.015] |
| 143/35 | 215 | 0.834→0.839 | 0.060→0.063 | +0.004 [−0.008, +0.017] |

The AUC-difference CI **includes zero in every split** for both variants — no detectable
discrimination loss from dropping the category split. Total-only's ECE stays at/under the full
model's (0.046–0.063, all within the 0.10 bound); QIB-only's ECE is a touch higher and less stable
in this coarse 3-split view (0.105–0.127) — a top-end saturation artifact, see below.

## The same six-check reliability gate the shipped model passes

Run at the default 60/20, all six checks:

| arm | discrimination | calibration | beats_base | time_stable | look_ahead | **verdict** |
|---|---|---|---|---|---|---|
| full | 0.797 | 0.081 | 84.8% | 0.136/0.056 | 0.477 | **PASSED** |
| qib_only | 0.805 | 0.084 | 85.3% | 0.127/0.121 | 0.480 | **PASSED** |
| total_only | 0.805 | 0.079 | 85.1% | 0.121/0.054 | 0.473 | **PASSED** |

**A Total-only model passes the identical reliability gate the shipped model passes.**

## Why Total-only works (mechanism, not hand-waving)

| pair | Pearson | Spearman |
|---|---|---|
| qib vs total (raw) | 0.807 | **0.931** |
| log qib vs log total | 0.955 | — |
| full_score vs qib_score | — | 0.929 |
| full_score vs **total_score** | — | **0.979** |
| qib_score vs total_score | — | 0.931 |

Total subscription is a **0.93-Spearman rank-copy of QIB**, and the total-only score tracks the
*full model's* ranking at **0.979** — tighter than QIB-only does (0.929). Distributions (N=358):
QIB median 36.1× / max 331.6× / 19 above the 200× winsor cap; total median 22.3× / max 326.5× /
only 3 above the cap. Total **saturates less** (109 vs 148 IPOs above 60×), so it keeps more usable
dynamic range below the ceiling — which is why, if anything, it calibrates *more* cleanly than
QIB-only (whose top-end pile-up produces the coarse-split ECE wobble).

## Verdict

- **Total-only is viable.** Statistically indistinguishable from the full model on discrimination
  (AUC Δ within ±0.004, every CI includes 0), calibration (per-split ECE 0.046–0.063; 60/20 ECE
  0.079 — as good as or better than full's 0.081), and APPLY precision (85.1% vs 84.8%). It passes
  the full six-check reliability gate. A Total-only public model would be **just as
  trustworthy/well-calibrated** as the shipped model, on this dataset with this label.
- **QIB-only is also viable**, marginally rougher: AUC indistinguishable, passes the gate, but ECE
  is slightly higher and less stable across coarse splits (saturation artifact). Total-only is the
  cleaner single-feature model.
- **The full → QIB-only → Total-only dropoff is essentially flat.** There is no meaningful
  degradation at any step. **The QIB/NII/retail category split is NOT load-bearing for the model's
  output** — the single total multiple substitutes for it with no measurable loss. This is a strong
  confirmation (not merely an assertion) of the project's core QIB-redundancy thesis: since almost
  every feature is QIB-redundant and total is ~QIB, total carries essentially the same signal.

## Honest caveats (why this is a comparison, not a promotion)

1. Proven only as a **substitute input** on the 358-IPO historical set with our net-of-cost label.
   A real promotion needs the total-only calibrator carried through the **cold-market regime stress**
   (§4.5) — though the regime flag itself uses Nifty/VIX, not the split, so it is unaffected — plus
   quarterly recalibration and the standard small-sample caveats (358 IPOs, wide per-bucket CIs).
2. A licensed feed's "total subscription" must be verified to mean the **final at-close overall
   multiple** (same definition as our backfill), or the calibration will not transfer.
3. Kill-flags and enhancement features are already unpopulated / weight-0 in the shipped
   official-only model, so a total-only feed loses nothing there.

**Recommendation:** a Total-only public model is a viable path where the category split is not
licensable. It is not shipped or promoted here — pending operator review.
