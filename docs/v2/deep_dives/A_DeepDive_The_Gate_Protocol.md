# Deep Dive #A — The Gate Protocol

*The reusable procedure for running any v2 score-feature candidate from hypothesis to verdict. This is the machinery Part IV-B refers to. It exists because the default outcome of a v2 candidate is a **logged negative**, and the only honest way to reach that verdict — or the rare "promote" — is a disciplined, identical-every-time gate. If you find yourself deviating from this to make a candidate look better, stop: that deviation is the failure. Grounded July 2026.*

---

## The one job of this protocol

Answer, for a candidate feature X: **does adding X to the official QIB-led model make it measurably better on clean, point-in-time data — enough that the improvement isn't noise?** Nothing else. Not "is X interesting," not "does the literature like X," not "does the point estimate go up." Only: earned or not.

The burden of proof is **entirely on X**. The null hypothesis is "X is redundant with QIB and adds nothing" — because that has been true for GMP, OFS, and valuation. X is guilty until the gate acquits it.

---

## Step 1 — Scope

Before any code: write down, in `docs/V2_PROGRESS.md`,
- what X is and the exact feature construction,
- where its data comes from and whether it is **point-in-time obtainable** (available at/before subscription close, no future leak),
- its research-verification status (✅ confirmed / ◐ lead / ❌ refuted) — **a ◐ lead is not a fact; verify the underlying claim before spending build effort**,
- the honest prior: *how* might X be redundant with QIB? (Almost always there's a channel — name it.)

If the data is not point-in-time obtainable, stop — X cannot be honestly tested and must not be built.

---

## Step 2 — Cheap probe

Before building clean infrastructure, get a quick, dirty read on whether there's *any* signal. Use whatever data is cheapest (even an aggregator table under the trust-boundary caveat). Compute a rough with-vs-without on a small slice.

- **Probe shows nothing** → shelve now, cheaply. Log the negative. Do not build the clean pipeline for a feature with no pulse. (This is the cheapest possible rejection and the most common good outcome.)
- **Probe shows a possible pulse** → proceed to Step 3. But treat the probe number as **optimistically biased** — cheap data is often leaky or dirty, which *inflates* apparent signal (the GMP leaky screen showed +0.133 that collapsed to ~0 on clean data). A promising probe is permission to invest in a clean test, not evidence of value.

---

## Step 3 — Data QA (establish trust BEFORE trusting the gate)

**This step is not optional, and skipping it is how you get a false result.** The gate is only as honest as the data feeding it. The valuation lesson is the canonical case: a mis-parsed peer P/E manufactured a calibration "benefit" on the loose sample that **evaporated** when the data was hand-QA'd down to trustworthy rows.

For X's backfilled data:
- **Report clean coverage honestly** — of N eligible IPOs, how many have a *trustworthy* value vs missing / ambiguous / artifact. Do not partial-fill or paper over gaps.
- **Sanity-bound the values** — reject implausible ones (e.g. a P/E of 500, a subscription multiple of 0). Flag the "no clean value" cases (e.g. loss-making → no P/E, no listed peer) and handle them as neutral-with-flag, never a forced number.
- **Hand-QA a sample against source** — spot-check extracted values against the actual RHP/exchange page. If the parser is silently grabbing the wrong field, you find it here, not after the gate lies to you.
- If clean coverage is **too low to trust**, say so, and treat X's gate result as **inconclusive** rather than a clean pass/fail.

The output of this step is a trustworthy dataset for X and an honest coverage number — or the finding that X can't be cleanly sourced (a legitimate "deferred, data-limited" outcome, as anchor was).

---

## Step 4 — The gate (the core measurement)

Run on the **same IPOs**, two arms, **only X differs** between them:

1. **Refit the calibrator in each arm.** The with-X arm gets a calibrator *refit to include X* — never bolt X onto the without-X calibrator with a hand-picked or prior weight (that violates the sacred rule and produces a lying probability). The fitted weight is an *output* of this step, not an input.
2. **Walk-forward, point-in-time.** Train on past IPOs, predict future ones, roll forward. No random K-fold (leaks future regime into the past). Reconstruct every feature as-of the decision time.
3. **Both metrics:** discrimination (**AUC**) and calibration (**ECE**). A feature can lift one and wreck the other; you need both.
4. **Bootstrap CI on the lift**, because N is small. Report the CI, not just the point estimate.
5. **≥3 train/test splits.** A keep/cut call that **flips across splits is not a result** — it's noise. (The brakes' gate ran 3 splits precisely to catch this.)
6. If X is proposed as a **kill-flag** rather than a score feature, the gate is different: does flagging X's condition **avoid losers** on the backtest (fewer/smaller listing-day losses among selected IPOs)? Test the *sign* too — the OFS lesson: its assumed-bad condition was actually associated with *better* listings, so a naive flag would have hurt.

---

## Step 5 — The decision rule

**Promote X into the shipped model only if ALL hold:**
- It improves at least one of {AUC, ECE} and **worsens neither**.
- The lift CI is **not just noise around zero** (a CI that always includes 0 across splits = not earned).
- The call is **stable across the ≥3 splits** (doesn't flip).
- If X is a black-box-enabling change, it clears the **interpretability bar** (Rule 8) — a marginal metric edge does not justify losing the grounded reason.

If promoted: X ships with its **fitted** weight (from Step 4's refit), the calibrator is the new gated one, and the reliability gate is re-confirmed. Log PROMOTED with the evidence.

**Otherwise: shelve.** Add X to the Gated & Rejected graveyard with result, sample, date, and the honest reason. Quarantine any backfill code in `research/` (excluded from build); if a scorer slot was wired for testing, leave it at weight 0 with the byte-equality confirmation. Log REJECTED.

**A candidate never ends in the state "in the model, ungated." It is PROMOTED (gated, fitted) or REJECTED (graveyard). There is no third state.**

---

## The anti-patterns that invalidate a gate (do NOT do these)

- **Tuning to make it pass** — adjusting weights, thresholds, or the feature construction against the test outcome until it looks good. This is overfitting to the answer; it produces a fake pass.
- **Picking the flattering split** — reporting the one split where X helps and ignoring the two where it doesn't. Report all splits.
- **Bolting X on with a prior weight** — the 0.1/0.1/0.05 trap. Unfitted weights on a calibrated model = a lying probability.
- **Trusting a dirty backfill** — skipping Step 3, so the gate measures parsing artifacts, not the feature.
- **Reading a ◐ lead as a fact** — the literature is a hypothesis source; your sample is the authority.
- **Re-litigating a graveyard feature** without new data and a fresh gate.

---

## Reference: what a clean gate report looks like

A promoted or rejected candidate should leave behind a table like this in `docs/`:

| split | AUC off→on | ECE off→on | AUC lift (95% CI) |
|---|---|---|---|
| 60/20 | 0.815→0.820 | 0.071→0.086 | +0.005 [−0.020, +0.035] |
| 50/15 | 0.829→0.828 | 0.066→0.074 | −0.001 [−0.022, +0.020] |
| 40/10 | 0.817→0.818 | 0.085→0.092 | +0.001 [−0.017, +0.021] |

…plus the clean-coverage number, the honest prior, and the one-line verdict. The example above (real, from the OFS gate) reads: **no lift, CI straddles zero every split, ECE slightly worse → NOT EARNED.** That is the modal v2 outcome, and reporting it plainly is the protocol working.

---

*Engineering/research reference, not financial advice. The gate exists to produce honest verdicts — most of them negative — never to justify a feature someone hoped would work.*
