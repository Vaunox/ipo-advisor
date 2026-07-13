# Check 3 — Total-only deployability verdict (closing synthesis)

*Phase-1 deployability investigation, branch `total-only-gate` (off `main`, nothing merged).
**Comparison/verification work throughout — the shipped calibrator was never touched**:
`models/calibrator.json` is git-proven byte-identical to `main` at every step (SHA1
`fa2635717bb0179e2b21ed17b5ade4e7d5b25848`). All code and reports live under `research/`.
This document stands on its own — it does not require reading the other three reports
(`TOTAL_ONLY_GATE.md`, `CHECK1_FIELD_VERIFICATION.md`, `CHECK2_REGIME_T3_STABILITY.md`), though
they hold the full backing detail. Engineering/research reference, not financial advice.*

## The question

The shipped model is subscription-led, built on the QIB/NII/Retail category split. That split is
**not licensable** from most real-world public data feeds — brokers and data vendors that expose
free/cheap developer APIs typically expose only a single **Total** oversubscription multiple. Before
any public-facing v3 work resumes, this investigation asked three questions in order:

1. **Does a model built on Total-only come close to the shipped full model?** (statistical parity)
2. **Does that model hold up under the same stress the shipped model was put through** — cold-market
   regimes and the T+3 settlement cutover? (robustness)
3. **Is there an actual, real-world source that legitimately provides a correctly-measured Total
   multiple?** (deployability)

## Evidence chain

### 1. Gate parity — Total-only is statistically indistinguishable from the shipped model

Same 358-IPO calibration set, same net-of-cost label, same expanding-window walk-forward, **Platt
calibrator refit per arm** — identical discipline to every other gate in `PROJECT_LOG.md`. Three
arms differ only in the scalar score fed to the calibrator: `full` (shipped QIB+NII+Retail scorer),
`qib_only` (QIB term alone, the intermediate rung), `total_only` (the same subscription
normalization applied to the total multiple).

| arm | OOS N | AUC | ECE | Brier | shuffled | APPLY@0.65 precision |
|---|---|---|---|---|---|---|
| **full** (shipped) | 298 | 0.797 | 0.081 | 0.170 | 0.477 | 84.8% [79.0%, 89.2%] |
| qib_only | 298 | 0.805 | 0.084 | 0.166 | 0.480 | 85.3% [79.6%, 89.7%] |
| **total_only** | 298 | 0.805 | 0.079 | 0.169 | 0.473 | 85.1% [79.2%, 89.5%] |

Per-split AUC-lift 95% CIs (paired bootstrap, N=2000) **include zero on every one of 3 splits** for
both reduced arms (max Δ +0.007). **All three arms pass the identical six-check reliability gate**
the shipped model has to pass — discrimination, calibration, beats-base-rate, time-stability,
look-ahead-collapse, abstention-exclusion.

**Why it holds, mechanistically:** total subscription is a 0.93-Spearman rank-copy of QIB, and the
total-only score tracks the *full model's own ranking* at Spearman 0.979 — tighter than QIB-only's
0.929. Total also saturates less against the winsorization cap (3 of 358 IPOs over the cap vs 19 for
QIB), which is why its calibration is, if anything, slightly cleaner than QIB-only's. This confirms —
not merely restates — the project's long-standing QIB-redundancy thesis: the category split is not
carrying information the total multiple lacks.

### 2. Regime + T+3 robustness — holds, with one specific, understood caveat

The shipped model was stress-tested through cold-market regime lineage and the T+3 settlement
cross-break (the two hardest checkpoints after the reliability gate itself). Total-only was put
through the identical shipped test functions. The harness was validated first: run through `full`,
it reproduced the committed regime and T+3 numbers **exactly**, before any total-only number was
trusted.

**Regime stress-test** (cold ≡ Nifty negative 3-month trend or drawdown at listing):

| model | Regime | N | Base | AUC | ECE | APPLY precision |
|---|---|---|---|---|---|---|
| full | All / Hot / Cold | 298 / 193 / 105 | 70% / 75% / 60% | 0.80 / 0.80 / 0.76 | 0.081 / 0.077 / 0.102 | 85% / 85% / 83% |
| total_only | All / Hot / Cold | 298 / 193 / 105 | 70% / 75% / 60% | 0.81 / 0.81 / **0.77** | 0.079 / 0.084 / **0.133** | 85% / 86% / 83% |

- **Ranking/selection edge fully preserved, even fractionally improved**, in every regime including
  cold. Cold APPLY precision is statistically indistinguishable from the full model's (83% vs 83%,
  heavily overlapping 95% CIs) — the actionable behavior an operator sees does not change.
- **The one real finding:** cold-regime calibration (ECE) is worse — 0.133 vs the full model's
  already-marginal 0.102 (both exceed the model's own 0.10 tolerance; total-only is ~30% worse
  relatively). This is not a new failure mode — it's the same "cold markets calibrate worse" class the
  shipped model already manages by design (a weight-0 regime flag, "cold market — probability less
  certain," flag-don't-force), just a somewhat larger gap.

**T+3 settlement cross-break:**

| model | shift | verdict |
|---|---|---|
| full | −0.060 | DIFFERENCE (tolerance 0.030) |
| total_only | −0.062 | DIFFERENCE (tolerance 0.030) |

Total-only's shift matches the full model's almost exactly, for the identical already-documented
reason: the pre-cutover slice's composition (the 2017-extension's colder-era IPOs) drives the
difference, not the T+6→T+3 settlement change itself. Total-only inherits this, it does not create a
new instance of it.

### 3. Sourcing — Upstox conclusively closed; NSE/BSE-direct is the standing recommendation

Tested Upstox (Analytics-Token developer API) as the concrete candidate for a licensed Total-only
feed, across eight rounds of verification (full detail in `CHECK1_FIELD_VERIFICATION.md`):

- ✅ **Definition matches.** Upstox's `total_subscription` is the same construct as our NSE-sourced
  final at-close overall multiple. Of 118 IPOs matched 1:1 against our backfill, when Upstox carries
  the final value it agrees to a fraction of a percent (recent-window median gap 0.57%).
- ✅ **Mainboard filtering works** (`issue_type=regular` cleanly separates from SME).
- ⛔ **But the data is unreliable, confirmed unfixable inside the API.** 30% of matched IPOs are off
  by >10%, predominantly Upstox reading *low* (a stale pre-close snapshot missing the final-day
  institutional surge). Tried and closed every obvious fix:
  - The details endpoint (`/v2/ipos/{id}`) was hypothesized to be fresher than the list endpoint —
    tested on 15 IPOs, returned the **byte-identical cached value** in every case. No in-API escape.
  - Tested the hypothesis that only *pre-API-launch* data is stale (Upstox's IPO API launched
    2026-05-23) — **falsified**: 2 of 10 IPOs closing entirely *after* launch were still wrong (one
    of them wrong in a new direction, Upstox too *high*, ruling out a single fixable mechanism). A
    ~15–20% failure rate persists even at the freshest edge tested.
  - Verified our own backfill wasn't the stale side of the comparison: live-refetched NSE directly
    (cache bypassed) and got 14/14 exact matches to our CSV, spanning IPOs 14+ months old — our data
    is confirmed clean, not merely self-consistent.
  - No adjustment factor is viable — errors are idiosyncratic per IPO (ratios 0.10–0.67×), not a
    constant offset.
- **Consequence:** Upstox cannot be trusted as a standalone source. A deployment on Upstox would need
  an **external cross-check** (NSE/BSE final, or a second independent tracker) before showing any
  probability built on its subscription value — at which point Upstox is providing UX convenience,
  not the authoritative number.
- **The category split itself turned out to be reachable, just not from a licensed source.** Upstox's
  *consumer website* (not the API) shows the full day-wise QIB/NII/Retail split — confirming the
  split's authoritative home is **NSE/BSE**, which publish it officially (our backfill already relies
  on it). This reframes the sourcing question: **NSE/BSE-direct licensing would unlock the full
  model, not merely total-only**, and is the standing recommendation for the vendor/legal
  conversation, ahead of any broker-API compromise.

## The one caveat and its mitigation

**Cold-market calibration is somewhat softer for total-only than for the full model** (ECE 0.133 vs
0.102 in the cold slice). This is a known failure-mode *class*, not a new risk: the shipped model
already ships a weight-0 cold-market flag that decouples the caveat from the score ("cold market —
probability less certain," flag-don't-force, never fitted to outcomes). A total-only deployment
inherits this exact mechanism and should apply it a touch more conservatively given the larger gap —
e.g. tightening the cold-flag threshold slightly, or explicitly downgrading confidence language in
the cold-market caveat text for a total-only build. No new engineering pattern is required; the
existing one just needs to be dialed a notch further for this variant.

## Verdict

**Total-only is a validated, ready-to-deploy foundation if and when public distribution is pursued
again — contingent on securing a licensed data source that actually delivers the correctly-measured
figure.** The model itself clears every bar the shipped model had to clear: it is statistically
indistinguishable from the full model on discrimination, calibration, and APPLY precision; it passes
the identical six-check reliability gate; and it survives the same regime and settlement-cutover
stress tests with only one bounded, already-understood caveat (softer cold-market calibration,
manageable with the existing flag-don't-force mechanism, applied a bit more conservatively). What is
**not** yet solved is sourcing: Upstox, the one concrete broker-API candidate tested, is conclusively
closed on data-quality grounds with no in-API fix, which leaves **NSE/BSE-direct licensing as the
standing recommendation** — the same investigation that closes off Upstox also reframes the prize,
since a real NSE/BSE license would unlock the full category-split model rather than forcing the
total-only compromise. Nothing here changes, ships, or is promoted: this is the technical
confirmation to carry into the legal/vendor conversation, not a decision to act on unilaterally.
