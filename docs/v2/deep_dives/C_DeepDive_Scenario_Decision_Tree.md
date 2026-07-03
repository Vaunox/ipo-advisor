# Deep Dive #C — The Scenario Decision Tree

*How the agent should navigate every situation that arises in v2 — without a human in the loop for each one. This encodes the judgment calls that were made by hand across v1's validation (regime, GMP, the brakes): what to do when a probe shows nothing, when data is brittle, when a lift looks real but might be noise, when a feature passes but costs interpretability, when a source breaks, when someone wants to re-add a rejected feature. Each scenario states the situation → the correct action → why. When a scenario genuinely isn't covered here, that is the signal to stop and ask the operator — do not improvise on a sacred invariant. Grounded July 2026.*

---

## How to use this

For any v2 candidate or event, find the matching scenario below and follow its action. The scenarios are grouped: **probing & gating**, **data problems**, **results interpretation**, **promotion & code hygiene**, **operational events**, and **escalate-to-human**. The governing spirit throughout: **the default action is the conservative one** — shelve, abstain, fail loud, don't ship — because the cost of a wrong "yes" (a lying probability, a shipped-but-disproven feature) is far higher than a wrong "no" (a shelved feature you can revisit).

---

## Group 1 — Probing & gating

**S1. Cheap probe shows no pulse.**
→ **Shelve immediately.** Log the negative in `docs/V2_PROGRESS.md`. Do NOT build the clean pipeline. *Why:* the cheapest rejection is the most valuable outcome; building infrastructure for a signal-less feature wastes effort and tempts later "but we already built it" reasoning.

**S2. Cheap probe looks promising.**
→ Proceed to the clean gate, but **treat the probe number as optimistically biased**. State in the log that it's a lead, not a result. *Why:* cheap/dirty data inflates apparent signal — GMP's leaky probe showed +0.133 that collapsed to ~0 clean.

**S3. The candidate is a ◐ research lead.**
→ **Verify the underlying claim before building.** Confirm it survives a proper check; weight ✅-confirmed candidates ahead of ◐ leads in the queue. *Why:* ◐ means "extracted but not verified" — it's a hypothesis, and your sample is the authority regardless.

**S4. The candidate was designed in the original blueprint / has literature support.**
→ **That is not a reason to add it.** It still faces the full gate; "planned" and "the literature likes it" are hypotheses, not evidence. *Why:* every rejected feature (regime, GMP, OFS, valuation) was designed-in and/or literature-backed. Design intent means *test it*, not *ship it*.

**S5. The candidate is a kill-flag, not a score feature.**
→ Use the **kill-flag gate** (does flagging the condition avoid *losers* on the backtest?), and **test the sign** — confirm the "bad" condition is actually associated with worse outcomes. *Why:* the OFS lesson — its assumed-bad condition (high OFS) was associated with *better* listings; a naive flag would have hurt.

---

## Group 2 — Data problems

**S6. The feature's data is not point-in-time obtainable (only available after the decision).**
→ **Stop. Do not build or test it.** A feature that can't be constructed as-of the decision can't be honestly gated and would leak. *Why:* point-in-time correctness is a sacred invariant; a leaky feature produces a backtest that lies.

**S7. The data can only be collected going forward (no free historical archive).**
→ **Start a collect-forward recorder now** (append-only, timestamped), decoupled from when the feature is gated. Use aggregator tables only for the cheap probe. *Why:* collect-forward-or-lose-it — waiting to collect means waiting again later (Deep Dive #B).

**S8. The backfill data is brittle / needs per-item judgment (e.g. peer P/E).**
→ **QA before trusting the gate.** Report honest clean-coverage; sanity-bound values; hand-QA a sample against source; flag "no clean value" cases as neutral-with-flag. If clean coverage is too low, mark the gate result **inconclusive**, not pass/fail. *Why:* the valuation lesson — dirty data manufactured a fake lift that evaporated on QA. A gate on bad data measures the parser, not the feature.

**S9. The data can't be cleanly sourced at all (e.g. API-rendered, needs a separate scrape project).**
→ **Defer as "data-limited."** Do NOT build a speculative scrape to test a feature with a strong redundancy prior. Log it deferred with its trigger condition. *Why:* the anchor decision — spending heavy sourcing effort to most-likely confirm "redundant, cut" is low expected value.

**S10. A user-supplied / BYOK feed offers a calibration-critical field.**
→ **Do not let it become authoritative.** Official NSE/BSE stays the source of truth for critical fields; BYOK is convenience/redundancy only, and the probability is withheld if inputs can't be proven to match the calibrator's feature contract. *Why:* trust-boundary + calibration-validity invariants; schema-presence ≠ semantic-equivalence.

---

## Group 3 — Results interpretation

**S11. Lift is positive but the CI straddles zero.**
→ **Not earned. Shelve.** The point estimate is not evidence; the CI including zero means "indistinguishable from no effect." *Why:* this is the modal outcome (GMP, OFS, valuation all did this). Reporting it as a pass would be manufacturing a result.

**S12. The keep/cut call flips across splits.**
→ **Not a result. Shelve** (or mark inconclusive and gather more data). *Why:* a finding that depends on which split you pick is noise, not signal — that's why ≥3 splits are run.

**S13. Lift looks real on the loose sample but disappears on the clean/QA'd sample.**
→ **Trust the clean sample. Not earned.** The loose-sample lift was artifact. *Why:* exactly the valuation case; clean data is the authority.

**S14. The feature passes AUC but worsens ECE (or vice versa).**
→ **Not earned** — the rule requires improving one and worsening *neither*. *Why:* a feature that sharpens ranking but corrupts calibration breaks the "70% means 70%" guarantee.

**S15. A black-box model (e.g. TabPFN) passes the metrics.**
→ Apply the **interpretability bar**: it must beat logistic by enough to justify forfeiting the grounded reason. A marginal edge → keep logistic. *Why:* the grounded reason is part of the product (Rule 8); a model that can't explain its verdicts is a worse product even at equal metrics.

**S16. A cold-market re-test of a hot-rejected feature (e.g. GMP) shows a lift.**
→ This is a **legitimately different question** and a valid promotion path *if* it passes the full gate on cold data with a real CI. Promote with the fitted weight; note it's regime-conditional. *Why:* "failed hot" ≠ "failed forever"; the cold-market question was always left explicitly open.

---

## Group 4 — Promotion & code hygiene

**S17. A candidate PASSES the gate.**
→ Ship it with its **fitted** weight (from the refit, never a prior), make the new calibrator the gated one, re-confirm the reliability gate, log PROMOTED with evidence. *Why:* only fitted-and-gated weights keep the probability honest.

**S18. A candidate FAILS the gate.**
→ Add to the Gated & Rejected graveyard (result, sample, date, reason). **Quarantine** its backfill code in `research/` (excluded from build); leave any scorer slot at **weight 0** with byte-equality confirmed. Log REJECTED. *Why:* preserve for possible future re-test without letting dead code ship or move the score.

**S19. Someone wants to wire a failed feature's data into live features "since we have it now."**
→ **Refuse unless it re-passes a fresh gate.** The zeroed weight + `research/` quarantine exist precisely to block this silent reactivation. *Why:* a disproven feature at a prior weight is a lying probability; the graveyard is not a suggestion.

**S20. A candidate is "in the model but never gated."**
→ **This state is illegal.** Resolve it: either gate it (→ promote or reject) or zero its weight and quarantine it. *Why:* every feature must be PROMOTED (gated) or REJECTED (graveyard) — there is no third state.

**S21. Tempted to tune weights/thresholds/construction to make a candidate pass.**
→ **Stop. That invalidates the gate.** Report the honest result. *Why:* tuning to the answer is overfitting to the test; it produces a fake pass that fails live.

---

## Group 5 — Operational events

**S22. An NSE / aggregator endpoint changes shape or starts failing.**
→ The schema-validation should have **raised** (failed loud). Fix the adapter; do not silently mis-map. Alert. *Why:* silent source drift poisons data invisibly; loud failure is the guardrail (no second NSE to corroborate against).

**S23. Ingestion gets blocked (cloud-IP / bot check).**
→ Surface loudly via the heartbeat; handle the session/cookie/UA handshake; consider a residential-ish egress. Do NOT fabricate or interpolate the missing data. *Why:* a gap you know about is recoverable; fabricated data is silent poison.

**S24. Live verdict accuracy departs from the gated numbers (rolling APPLY precision / ECE drifts).**
→ Alert; investigate; trigger a **recalibration** if it's a regime shift. Do not quietly let the live model diverge from its gated guarantees. *Why:* the calibrated promise only holds if it's monitored and refreshed.

**S25. A SEBI rule changes (anchor %, T+3, MPO tiers, when-issued platform launches).**
→ **Era-flag** affected features (pre/post-rule books are structurally different); for the when-issued platform, evaluate adopting it as an official GMP substitute. Verify the rule against primary text before encoding. *Why:* a structural break silently mixes two regimes into one feature.

---

## Group 6 — Escalate to the human (do NOT improvise)

Stop and ask the operator when:

**S26.** A change would touch a **sacred invariant** in a way not explicitly blessed here (calibration, advisory-only, point-in-time, trust boundary). *Never* improvise on these.

**S27.** A **transaction-capable credential** (broker trading token) is involved. Do not store it; surface the advisory-only conflict and ask.

**S28.** A candidate **passes the gate but the result is surprising** (a feature you expected to be QIB-redundant shows a strong, stable lift). Report it, show the full evidence, and ask before promoting — a surprising pass warrants a second look for hidden leakage.

**S29.** The situation genuinely **isn't covered** by any scenario here, and the conservative default (shelve / abstain / fail loud) isn't obviously right. *Why:* the absence of a rule on a high-stakes call is itself the signal to get a human — better a paused candidate than an improvised invariant breach.

---

## The one-line summary of every scenario

**When uncertain, take the conservative action: shelve the feature, abstain on the number, fail loud on the data, and don't ship.** A wrong "no" is a feature you revisit later. A wrong "yes" is a probability that lies to the operator. The whole point of v2's discipline is that those are not symmetric — so the tie always goes to "no."

---

*Engineering/research reference, not financial advice. This tree encodes conservative defaults; when a genuinely novel high-stakes situation arises, the correct move is to stop and ask, not to improvise.*
