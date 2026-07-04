# MASTER BLUEPRINT — IPO Advisor v2 (Execution & Gate Playbook)

### Claude Build Handoff Document — v2

*v2 is **not** a linear build. v1 shipped a known architecture; v2 is a **research backlog where the default outcome of every candidate is "shelved with a logged negative."** This document tells the agent how to run each candidate through its gate and build it **only if it earns its place** — and how to navigate every scenario that arises. "Finish" means: every candidate has been gated and either earned its place or been logged as a negative. It does **not** mean every feature got built. Grounded July 2026.*

---

## HOW TO USE THIS DOCUMENT WITH CLAUDE

Work it as **two separate tracks**, in this order of safety:

- **Track A — BUILD items** (Part IV-A): things that do **not** touch the calibrated score, so they need no gate — just correct, tested building. Safe to build like v1 phases.
- **Track B — GATE items** (Part IV-B): candidate score features. Each is a **hypothesis run through the gate protocol** (Deep Dive #A), and built into the shipped model **only if it passes**. The default expected outcome is failure.

**The single most important instruction:** never promote a Track-B candidate into the shipped model on the basis of "it was planned," "the literature supports it," or "the point estimate looks good." A candidate enters the score **only** after passing the gate on clean, point-in-time data with a CI that isn't noise around zero. When in doubt, shelve and log.

**At the start of a candidate, tell Claude:**
> "Follow the Inviolable Rules (Part I) and the gate protocol (Deep Dive #A). We're evaluating candidate X. Run its gate. Report the with-vs-without table with CI. Promote **only** if it passes; otherwise add it to the Gated & Rejected graveyard with the result. Do not touch the shipped calibrator until the result is in."

---

# PART I — INVIOLABLE RULES (carry into every v2 change)

These are inherited from v1 and are non-negotiable. Every v2 change is checked against all of them.

1. **Calibration is sacred.** No feature enters the *number* until it has earned its place through the gate, and the calibrator is **refit** to include it. Never bolt a feature onto the existing calibrator with a hand-picked or prior weight — that produces a calibrated-looking probability the reliability gate never blessed. A weight that wasn't fit on data containing the feature is a guess wearing a number.
2. **A feature stays out of the score until calibration earns it.** The proven-safe pattern for anything not-yet-earned: wire it at **weight 0** (annotation/plumbing only), prove byte-for-byte that it doesn't move the probability (`MAX |Δprob| = 0.0`, exact, non-vacuous), and only promote to a real *fitted* weight after a gate pass.
3. **Point-in-time correctness.** Every feature uses only data available at/before the decision (subscription close). The label never leaks into an input. The backtest reconstructs as-of snapshots. A future value (a later Nifty close, a post-listing price) must never bleed into a past IPO.
4. **Advisory-only, structurally.** No order/action/transaction path anywhere. This includes credentials: never store a transaction-capable token (e.g. a broker trading access token) — the guarantee must stay structural ("nothing in it *can* transact"), not a policy promise.
5. **The engine abstains when blind.** Missing a critical input → `INSUFFICIENT_SIGNAL`, never a fabricated number. New optional features are optional (missing → neutral); they never become new critical inputs without deliberate decision.
6. **Data trust boundary.** Label/backtest-critical fields are cross-checked against official NSE/BSE; never taken from a single unvetted aggregator. A user-supplied feed never becomes authoritative for a calibration-critical field.
7. **Rejected features stay rejected.** Anything in the Gated & Rejected graveyard (Part III) is not re-litigated without genuinely new data AND a fresh explicit gate. Its code is quarantined in `research/` (excluded from the build), weights zeroed. Do not re-add on a hunch.
8. **Interpretability is part of the product.** The grounded reason ("QIB 38×") is a feature, not a nicety. A change that forfeits traceability (e.g. a black-box model) must clear a higher bar than a marginal metric gain.
9. **Honesty about outcomes.** The default v2 result is a logged negative. That is the discipline working, not a failure. Do not tune, cherry-pick a split, or reframe to manufacture a pass.

---

# PART I-A — STANDING RULE: live/forward data-recording jobs are DEFERRED

*Governs the whole backlog — read before picking up any item. Operator decision, 2026-07-03.*

**The operator is not running standing scheduled or daily data-recording jobs.** Therefore every candidate or task that requires **collecting data forward over time** — a recorder, a scheduler, an always-on job, or any "bank data going forward" dependency — is **DEFERRED**. Not rejected on the merits; just not pursued now, because the operator won't run the collection infrastructure they need.

**Deferred under this rule:**
- **A1** — day-wise subscription recorder (removed; feature not pursued).
- **A2** — live subscription auto-ingestion as a standing job (cancelled; the app's in-session refresh already covers live verdicts).
- **B1** — subscription trajectory / velocity (needs A1's banked history → deferred).
- **The GMP recorder** (always-on forward GMP collection) and everything depending on it: **B4** (GMP cold-market re-test), **B5** (multi-source GMP confidence + spike-collapse flag) — all deferred, because they require forward GMP banking.

**Explicitly NOT affected by this rule** (these are not forward-recording jobs):
- **The shipped app's own live ingestion (`live.py`)** — it refreshes subscription and shows live verdicts *while the app is open*; it is not a standing recorder and stays.
- **A4 occasional rituals** — quarterly recalibration and verdict-accuracy monitoring are run manually/periodically by the operator, not as daily jobs; they stay.

**What remains actionable in v2** (no live-recording dependency): the allotment-EV layer (**A3**), India VIX (**B2** — free point-in-time series, no recording), cheap feature adds (**B3** — data already ingested), RHP kill-flags/context (**B6** — static filings), graded regime tiers (**B9** — annotation), the TabPFN bake-off (**B7**), the conformal layer (**B8**), and ops hardening (**A4**).

**To lift this deferral later:** the operator decides to run a recorder (a local scheduled task or an always-on service), at which point the relevant deferred items become actionable again. Nothing here is rejected on the merits — it's **deferred on operational choice**.

---

# PART I-B — STANDING RULE: branch-first; main stays clean and only takes what earns it

*Governs all v2 work. Operator decision, 2026-07-03.*

**All v2 work happens on a branch, never directly on `main`.** `main` always stays green and shippable. Nothing merges to `main` until it has passed the correct standard **for its track**:

- **BUILD-track items** (no calibration impact — e.g. allotment-EV, ops hardening): merge to `main` only when the code is complete, all tests pass, and ruff/black/mypy (full tree) are clean. **Working + green = merge.**
- **GATE-track items** (candidate score features — e.g. VIX, cheap adds, TabPFN): green tests are **necessary but not sufficient**. The feature merges into the shipped model **only if it PASSES its gate** (with-vs-without, walk-forward OOS, CI not straddling zero, calibrator refit). A gate item that is perfectly working code but **fails its gate does NOT merge** — its code is quarantined in `research/` (excluded from the build) and the negative is logged. **"It runs" never earns a merge; "it earned its place" does.**

**Workflow for every v2 item:**
1. Create a branch off `main`.
2. Build/test the item there in isolation.
3. Validate to the right standard (green tests for BUILD; a **passed gate** for GATE).
4. **Pause and report the result to the operator before merging** — show tests and, for gate items, the with-vs-without table with CI.
5. Merge to `main` only on **operator approval** and only if it earned it. Otherwise **quarantine + log**; `main` is untouched.

`main` never receives unvalidated, ungated, or gate-failed code. **The default path for a gate candidate ends in `research/`, not `main`.**

**This formalizes how v1 was already built.** v1 shipped phase-by-phase, each gate tagged (`gate-0-foundation` … `gate-7-app`), with steps landing "green on [their] own branch, merged on approval" (`docs/PROGRESS.md`, Phase 6). Its gate-**failed** candidates — OFS / valuation / anchor (branch `enhancement-gate`) and GMP — were **quarantined in `research/` and zeroed, never merged into the score** (`docs/ENHANCEMENT_GATE.md`, `research/README.md`). v2 makes that lived practice the explicit, non-negotiable standard.

---

# PART II — THE GOVERNING GATE (every Track-B candidate)

Full protocol in **Deep Dive #A**. The essence, repeated here because it governs everything:

1. **Research / scope** — what is it, where does the data come from, is it point-in-time obtainable.
2. **Cheap probe** — a quick read on whether there's any signal at all, before building clean infrastructure. A null probe → shelve now, cheaply.
3. **Data QA** — establish the data is *trustworthy* before trusting the gate. (The valuation lesson: a mis-parsed feature manufactured a fake lift that evaporated on hand-QA'd data. Garbage-in poisons the gate itself.)
4. **The gate** — walk-forward OOS, point-in-time, same IPOs scored **with vs without** the feature (only that feature changes), calibrator **refit** each arm. Measure calibration (ECE) **and** discrimination (AUC), with a bootstrap CI. Run ≥3 splits; a call that flips across splits is not a result.
5. **Promote only if** it improves at least one metric and **worsens neither**, with a CI that isn't just noise around zero.
6. **Else shelve** — add to the Gated & Rejected graveyard with result, sample, date, and reason.

**Two hard-won lessons that frame the whole backlog:**
- *More data only helps if it adds signal your existing features don't already carry, at the horizon you predict (1–2 day flip).*
- *Assume every candidate is redundant with QIB until the gate proves otherwise.* Institutions price public information before they bid, so a "new" signal is often already inside subscription demand. This sank GMP, OFS, and valuation. It is the null hypothesis.

---

# PART III — GATED & REJECTED (the graveyard — do NOT re-litigate)

*Tested on real data, failed the gate. Not open candidates. Do not re-add, re-weight, or re-test without genuinely new data (cold market / materially larger sample) AND a fresh explicit gate — and even then, expect the same result unless the data situation truly changed. Research leads that point back at these are hypotheses the gate already answered.*

| Rejected | Result | Sample / date | Why |
|---|---|---|---|
| `market_regime` as a score feature | CUT → weight 0 (flag-only) | OOS walk-forward | Regime-aware / per-regime calibration didn't converge on the thin cold sample. Kept live as annotation only. |
| GMP (hot-market) | NOT EARNED | Real point-in-time, hot N≈99/39 OOS | Lift ≈ 0, CI straddles zero; earlier +0.133 was leakage. Echoes QIB. (Cold re-test is a *different* open question — Track B.) |
| `ofs_fraction` | CUT (both ways) | Clean backfill, hot N=293 | No lift, ECE worse; kill-flag rationale **backwards** (high-OFS lists *better* — 17% vs 26% loss). |
| `relative_valuation` | NOT EARNED | Hand-QA'd N=93, hot | CI includes zero; apparent lift was outlier artifact, evaporated on clean data. |
| `anchor_quality` | Deferred, data-limited | — | Anchor list not cleanly sourceable; blueprint's "most redundant with QIB"; both siblings failed on redundancy. |
| B3: NII split (sNII/bNII) | NOT EARNED | Cached NSE raws, hot N=235 | AUC lift ≈0, CI straddles zero, keep/cut flips — the small/big split adds nothing beyond aggregate NII (QIB-redundant). See `docs/B3_GATE.md`. |
| B3: bucketed issue size | NOT EARNED | Chittorgarh, hot N=293 | Positive but small lift; CI includes zero on 2/3 splits and the call flips — the *least-unpromising*, still not earned. |
| B3: pricing-vs-band (cut-off vs band top) | **NOT EARNED — structural** | Chittorgarh, N=293 | **292/293 mainboard IPOs price the cut-off at the band top** → the voluntary-underpricing-via-cut-off channel **does not exist for mainboard book-builds**. Near-constant feature (lift +0.000). This closes the **entire cut-off-pricing idea category** — a permanent market fact; do not re-chase without evidence the pricing behaviour changed. |
| B3: BRLM reputation (point-in-time league share) | NOT EARNED | Chittorgarh, N=292 | AUC lift is noise (CI straddles zero). **ECE improved (0.087→0.068) but the discrimination lift was noise → not earned** (calibration alone is not a pass). Built **leakage-safe** (point-in-time league table) → **no fake lift**, validating the leakage discipline (cf. GMP's leaked +0.133 — an honest construction makes a redundant feature show ~zero, not a fake signal). |

**Code status:** quarantined in `research/` (excluded from build), scorer slots inert at weight 0 (`MAX |Δprob| = 0.0` confirmed), evidence in `docs/` (`B3_GATE.md`, `ENHANCEMENT_GATE.md`, `GMP_GATE.md`). B3 gate scripts (`run_b3_gate.py`, `gate_b3_deferred.py`) live in `research/` too. Cannot ship or move the score.

---

# PART IV-A — BUILD TRACK (no gate; build like v1 phases)

These do **not** touch the calibrated probability, so they need correctness + tests, not a gate. Each is one commit, green tree, tagged.

## A1. Start banking DAY-WISE subscription NOW ⏱️ (do first — clock-dependent)
> ⛔ **DEFERRED — Part I-A (standing rule).** Built, then **removed**; feature not pursued (no gate-usable historical day-wise subscription exists — see `V2_PROGRESS.md`). Lift only if the operator opts to run a forward recorder.

Official historical day-by-day subscription buildup is **not reliably archived free** — it can only be collected going forward. The best untested score candidate (Track B: subscription trajectory) depends on this data existing. So this is an **immediate collect-forward action**, independent of when trajectory is gated. Poll `ipo-active-category` with `updateTime`; append-only; same discipline as the GMP recorder. **Full spec: Deep Dive #B.**
**GATE A1:** day-wise subscription rows land append-only for a live IPO, timestamped, no overwrite; a re-run produces no duplicates.

## A2. Live subscription auto-ingestion
> ⛔ **DEFERRED / CANCELLED — Part I-A (standing rule).** Not built. The app's in-session `live.py` refresh already shows live verdicts while the app is open; a standing auto-ingestion job is not run. Lift only if the operator opts to run a standing service.

Wire the existing `ipo-active-category` source into the scheduler so subscription refreshes automatically during the bidding window (advisory *service*, not *script*). Respect the T+3 close-day cutoffs (Deep Dive #B) for when the "book closed" cycle fires. Build defensively — NSE's endpoint is an undocumented internal API (session/cookie/UA handling, cloud-IP blocking, schema-validate + fail loud).
**GATE A2:** subscription refreshes on cadence during an open book; schema-validation raises on an unexpected shape; the book-closed cycle fires at the correct cutoff.

## A3. Allotment-probability / expected-value layer
The biggest decision-quality upgrade. Verdict today says "will it list positive?"; the operator's real question is **expected net gain per application = P(allotment) × net listing gain − opportunity cost of blocked funds**. P(allotment) is computable from the retail subscription ratio + lot structure already ingested. It's a **downstream computation on the probability, not a change to it** — so it doesn't touch the calibrator.
**Correctness burden (this is its "gate"):** validate P(allotment) and the opportunity-cost term against **historical allotment outcomes** before it drives any decision. Under T+3, ASBA funds unblock at T+3 — the blocked-capital term is ~3 days (Deep Dive #B).
**GATE A3:** P(allotment) reproduces known historical allotment ratios within tolerance on a back-check; the EV output is displayed as a distinct, clearly-labeled figure (not confused with the calibrated probability).

## A4. Operate-phase hardening (standing ops, from launch)
- **Live verdict-accuracy monitoring** — rolling APPLY precision vs the backtest number, rolling ECE on realized outcomes; alert on departure.
- **Scheduled recalibration ritual** — re-run the Phase-4 calibration quarterly and after regime shifts, via the versioned calibrator machinery. Encode the **T+3 structural break** (the 2021+ sample straddles the T+6→T+3 mandatory cutover, Dec 1 2023) as a `t3_regime` dummy; check calibration stability across the break.
- **Data-source drift monitoring** — the recorder heartbeat model, applied to every scraper/feed.
- **Housekeeping** — httpx/starlette pin; forward NSE holiday sets.
**GATE A4:** monitoring alerts fire on injected drift; a dry-run recalibration reproduces the current calibrator; the t3 dummy is present and its cross-break stability is reported.

---

# PART IV-B — GATE TRACK (hypotheses; build only if the gate passes)

Each runs the Part-II / Deep-Dive-#A protocol. **Default expected outcome: logged negative.** Ordered by value-and-safety. Do not skip the cheap probe or the data-QA step.

## B1. Subscription trajectory / velocity ⭐ (best untested candidate — but needs A1's data)
> ⛔ **DEFERRED — Part I-A (standing rule).** Needs A1's banked day-wise history, which is not being collected. Lift when forward collection resumes.

**Hypothesis:** the *shape* of how subscription built (QIB surge timing, day-by-day velocity, late vs early demand) carries signal beyond the final multiple — right horizon, and not obviously QIB-redundant (the final number doesn't encode *how* it got there). Test a trajectory × issue-size interaction (research lead ◐).
**Blocked on A1** — you can't gate this until day-wise history is banked. Cheap probe may use aggregator day-wise tables (trust-boundary rules), but the durable path is A1.

## B2. India VIX ⭐ (do the safe half first)
**Two uses:** (1) **flag-enrichment (safe, no gate):** blend Nifty-trend + VIX into the regime *flag* at weight 0 — annotation-only, prove with the byte-equality test; (2) **score feature (full gate)** afterwards. Free, point-in-time-clean data (NSE daily series). **Honest prior:** VIX may partly echo through cautious QIB bidding — measure, don't assume.

## B3. Cheap feature adds (bundle into one recalibration pass; verify ◐ leads first)
Each is a separate arm through the gate; all are ◐ research leads → **verify the claim before building**, and expect QIB-redundancy:
- **NII split (sNII/bNII)** as separate features — cheapest, data already ingested.
- **Pricing-vs-band** (cut-off vs band-top — the "voluntary underpricing" channel).
- **BRLM (lead-manager) reputation** — automatable from league-table market share.
- **Bucketed issue size** — literature finds issue size *positively* related to underpricing (contra folk wisdom).

## B4. GMP cold-market re-test (the deferred Phase-5 question)
> ⛔ **DEFERRED — Part I-A (standing rule).** Requires forward, cold-regime GMP from the always-on GMP recorder, which is not running. Lift when the recorder resumes.

GMP failed the *hot* gate; the open question is whether it earns its weight **when QIB is weak** (cold market). **Commit to a trigger** ("re-run after N cold-regime IPOs banked"), don't leave open-ended. Re-run the exact gate on cold OOS data. Also test an **early-window GMP variant** (day 1–2, before subscription accumulates) — a narrower surviving lead. **Blocked on cold data from the recorder.**

## B5. Multi-source GMP confidence / spike-collapse flag
> ⛔ **DEFERRED — Part I-A (standing rule).** Requires forward, multi-source, day-by-day GMP from the always-on recorder, which is not running. Lift when the recorder resumes.

- **Multi-source divergence** as a confidence/abstention signal (the v1 GMP test was single-source). Blocked on recorder multi-source data.
- **Spike-then-collapse manipulation flag** — a **kill-flag**, not a score input (independent of GMP's rejected ranking value). Gate: does flagging spike-collapse IPOs avoid listing-day losers? Blocked on recorder day-by-day GMP.

## B6. RHP / filing-text mining → kill-flags + operator context (NOT a score feature)
**Default: do not add as a score feature** (fundamental, wrong horizon, likely QIB-redundant). Worthwhile uses: **auto-populate kill-flags** (promoter litigation, adverse audit opinions, related-party, regulatory actions — automating the manual flag) and **operator context** (surface RHP facts alongside the verdict; never touches the number). One ✅-confirmed paper shows prospectus text *did* predict listing-day underpricing, and its dataset is free on Hugging Face → the **cheap probe is nearly free**; run it before the default-skip stands. Gate (kill-flag use): do the flags avoid losers on the backtest?

## B7. Model-architecture bake-off (one-day experiment)
**Keep the logistic core** — research is unambiguous that logistic is stable at your sample size and flexible ML overfits below ~10× the events-per-variable. The one credible challenger is **TabPFN v2**; run it through the same gate. **It must clear a higher bar than AUC/ECE:** adopting a black box forfeits the grounded reason (Rule 8), so it must win by enough to justify losing interpretability. Most likely (and fine) outcome: logistic stays, question closed with evidence.

## B8. Regime-aware calibration — revisit when cold data accrues
Currently annotation-only (didn't converge OOS on thin cold data). With enough cold history, re-face the same bar (OOS cold ECE within tolerance). A complementary honesty layer — **weighted conformal prediction** — gives distribution-free uncertainty bands that handle regime shift *without* requiring the per-regime calibrator to converge; worth evaluating as an add-on.

## B9. Graded regime-flag tiers (annotation polish — safe anytime)
Replace the binary cold flag with graded tiers (normal/soft/cold), each with its own caveat. Pure annotation (weight 0, score never moves) — the thin-sample problem does **not** apply. Untuned round-number boundaries; read-only per-tier count check; extend the exact-equality test to every tier. Isolated small commit.

---

# PART IV-C — PROPOSED, NOT ACCEPTED (resolve invariants before building)

## BYOK data-integration (bring-your-own API key)
Recorded faithfully but **blocked**, because as specified it collides with two sacred invariants: (1) a stored broker **access token is transaction-capable** → breaks advisory-only-structurally (Rule 4); (2) a user feed can supply inputs the calibrator was never fit on while the app shows a gate-blessed-looking number → breaks calibration validity (Rule 1), and schema-*presence* validation ≠ semantic-*equivalence* validation. **The shape that could pass:** BYOK for **non-critical convenience data only** (calendar/schedule/discovery), official NSE remaining authoritative for every calibration-critical field, probability withheld whenever inputs can't be proven to match the calibrator's feature contract. Do not build the broker-token profile or user-feed-drives-verdict-inputs as specified.

---

# PART V — PARKED / WATCH

- **GMP recorder (always-on forward GMP collection) — DEFERRED (Part I-A).** The separate always-on GMP-banking job is not being run, so no new forward / cold / multi-source GMP accrues; **B4** and **B5** (which depend on it) are deferred with it. Lift when the operator opts to run the recorder. (v1 already assessed the paid IPOMatrix archive as "poor value; not a sanctioned ongoing source" — see `docs/GMP_GATE.md`.)
- **SME segment model — deferred.** Most-manipulated segment; research measures SME ~7× noisier than mainboard, and the mainboard GMP-proxy relationship doesn't transfer. If ever taken up: own dataset, own calibration, own gate — never mixed into the mainboard calibrator.
- **SEBI "when-issued" pre-listing platform — watch.** If launched, it becomes an official free GMP substitute; adopt and retire the recorder's scraping.
- **Mega-IPO MPO tiers — watch** the issue-size feature's tail behavior forward (affects only the largest IPOs).

---

# PART VI — PRIORITY ORDER (what to actually do)

**v1 is shipped (Phase 7 done).** Under the **Part I-A standing deferral**, the forward-recording items — **A1, A2, B1, B4, B5, and the GMP recorder** — are **DEFERRED**. The actionable order among the rest:

1. **A3 — allotment-EV layer** — the biggest decision-quality upgrade; a downstream computation on the probability, no recording dependency.
2. **B2 VIX flag-enrichment** (safe half) — free, point-in-time, annotation-only proof.
3. **B3 cheap adds + B7 TabPFN + B8 conformal** — one recalibration pass; verify ◐ leads first; TabPFN must clear the interpretability bar.
4. **B6 RHP kill-flags/context** — after the free HF-dataset probe.
5. **B9 graded regime tiers** — anytime, isolated commit.
6. **A4 standing ops** — quarterly recalibration + verdict-accuracy monitoring (operator-run rituals, **not** daily jobs) and the T+3 `t3_regime` dummy; parked items stay parked until triggers fire.

**Deferred until the operator opts to run a recorder (Part I-A):** **A1** (removed), **A2** (cancelled — the app's in-session `live.py` refresh already covers live verdicts), **B1** (needs A1's history), and **B4 / B5 + the GMP recorder** (need forward GMP banking).

---

# PART VII — PROGRESS LOG
*Maintain in `docs/V2_PROGRESS.md`. Every candidate ends in one of two states: PROMOTED (with fitted weight + gate evidence) or REJECTED (graveyard row). Never "in the model, ungated."*

| Date | Candidate | Track | Outcome | Evidence | Notes |
|---|---|---|---|---|---|
| | | A/B | built / promoted / rejected | | |

---

*Reference docs: Deep Dive #A (the gate protocol), Deep Dive #B (collect-forward data & the recorder), Deep Dive #C (the scenario decision tree). Engineering/research reference, not financial advice. A calibrated probability is an estimate, not an assurance; the system is advisory only and places no orders.*
