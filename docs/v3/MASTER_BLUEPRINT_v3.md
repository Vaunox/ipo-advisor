# MASTER BLUEPRINT — IPO Advisor v3

### Claude Build Handoff Document — v3

*v3 is a **BUILD-track document**. Unlike v2 (a gate-running research playbook where the default outcome was a logged negative), **nothing in v3 touches the model.** No feature here enters the score, adjusts the calibrator, or changes a probability. That makes v3 fundamentally simpler and safer than v2 — but it does NOT relax the discipline: the invariants below still govern every line of code, and "it doesn't touch the model" is a claim that must be **proven**, not assumed. Grounded July 2026.*

---

## HOW TO USE THIS DOCUMENT

v3 has four parts, and they are ordered by risk, not by excitement:

- **Part II — Infrastructure** (the VM data layer). Highest risk, because it changes where data comes from.
- **Part III — Bugs.** Second, because one of them is actively misleading the user *today*.
- **Part IV — New non-model features.** Display/routing only.
- **Part V — Cosmetic/UI.** Lowest risk, do last.

**Standing process rule for v3 (operator-set):** for the bug-fix work in Part III and any ambiguity elsewhere — **ask, solve, confirm, then move to the next.** Do not batch fixes silently. If an issue is unclear or a design decision is genuinely open, stop and ask the operator rather than picking a default.

---

# PART I — INVIOLABLE RULES (carried forward, unchanged)

Every rule from v1/v2 still applies. The three that v3 work is most likely to brush against:

1. **Calibration is sacred.** No v3 item may alter the scorer, the calibrator, feature construction, or a probability. Every v3 branch must **prove** the scoring path is byte-identical (git-proven: nothing under `service/model|calibration|features|core`, `models/`, `config/`). This is not a formality — it is the check that makes "non-model feature" a fact rather than an intention.
2. **Advisory-only, structurally.** No order-placement path, ever. (Note: this is now doing *more* work than when it was written — SEBI's 2026 algorithmic-trading framework, mandatory from April 2026, regulates automated *order execution* and requires exchange-issued Algo-IDs and broker intermediation. The app has never placed orders, so it sits outside that regime entirely. Do not introduce anything that changes this.)
3. **Nothing in the UI may lie about what it is doing.** A control that claims success without acting, an indicator that asserts freshness it doesn't have, a toggle that persists but does nothing — these are worse than absent features, because they manufacture false confidence. This rule is why Bug #1 (Part III) is the highest-priority item in v3.

**New for v3 — the data-provenance rule:** the app may now get its data from the VM *or* from local scraping. It must **always be true and visible** which path is in use. A degraded/fallback state must never be silent.

---

# PART II — INFRASTRUCTURE: THE VM DATA LAYER

## The architecture (decided)

- **The VM is a pure data layer — the WHOLE data plane, not just NSE.** It runs **every fetcher the app depends on** — NSE ingestion **and** the Upstox per-IPO context refresh (`refresh_context.py`: registrar, RHP, lot size, isin, industry) — durably archives **input** (raw scraped data) and **output** (verdicts/history), and **serves every store the app reads through ONE read-only API**. Nothing else runs on it.
- **One transport for all stores (decided): a read API, not file-sync.** The app reads each store over the same read-only HTTP mechanism. Adding a future store must never mean adding a second transport.
- **The model, calibrator, scoring, UI, builds, and the recalibration ritual all stay in the user's local app.** The VM is never capable of running the model. This division is deliberate and load-bearing — it keeps the VM's resource envelope trivial and keeps the model where it has always been.
- **VM is PRIMARY.** The app fetches from the VM first.
- **Local scraping (the current pipeline) is the FALLBACK.** It is never removed. If the VM is unreachable, the app scrapes/refreshes directly, exactly as it does today. This holds for **every** store the VM serves, not only NSE.
- **The Upstox token lives on the VM** (as an env var there), so `refresh_context.py` runs on the VM. The token is **never** in the packaged app and **never** committed. (`refresh_context.py` was built VM-runnable from day one — pure Python, env token, `--data-dir`, no desktop assumptions — so it adopts as-is, no rewrite.)
- **Spec:** Oracle Always Free, 1 vCPU / 1 GB, Mumbai region.

## V3-1. VM setup and the data plane — NSE ingestion + Upstox context + read API

**Scope (operator-corrected): V3-1 is the full data plane, not just NSE.** The VM runs every fetcher and serves every store the app reads. Three parts:

**(a) NSE ingestion.** Move (or replicate) the existing NSE ingestion to run on the VM, carrying the **identical discipline** the local `nse.py` already has: cookie/UA handshake, schema-validate, **fail loud** on drift. This is more important on the VM than locally, because nobody is watching it in real time.

**Verified fact (operator-tested):** NSE does **not** block the VM's Mumbai-region datacenter IP — no proxy or rotation needed. This is the condition that makes VM-primary viable. **It is not a permanent guarantee.** NSE may tighten blocking at any time. The monitoring in V3-3 exists precisely so that if this changes, you find out in hours, not months.

**(b) Upstox per-IPO context refresh.** The VM also runs `scripts/refresh_context.py` on a cadence (the display-only registrar / RHP / lot size / isin / industry cache). It was **deliberately built VM-runnable** (pure Python, env `UPSTOX_TOKEN`, `--data-dir`, no desktop assumptions) — **adopt it as-is, no rewrite.** The token is an env var on the VM only.

**(c) The read API — one read-only mechanism for every store.** The app fetches both stores (NSE records/history + the Upstox context) from the VM over a small HTTP API, on the following non-negotiable requirements:

- **Read-only, structurally.** GET only, no mutation route — the same guarantee the engine's local API already holds. The app reads from the VM; it can **never** make the VM act. Do **not** reintroduce the mutation surface that was deliberately refused when Option 1 (shell-owned stdin trigger) was chosen for BUG 1's refresh.
- **Degrade honestly and visibly.** VM request timeout **10s**, **2 retries**, then fall back to local scraping/refresh **and show the fallback indicator** ("running on local data — VM unreachable"). Never a silent degrade. Reuse the freshness/state pattern from BUG 1 (`ingest_state` / `GET /status`) and V3-6 (`field_state`) rather than inventing a second one.
- **Freshness travels with the data.** Each store carries its **own** last-successful-refresh timestamp in its payload, so the staleness-honesty rule is **identical** whether the data came from the VM or the local fallback — one staleness rule, evaluated the same way on both paths, not two.

**GATE V3-1:** the VM fetches NSE **and** refreshes the Upstox context on schedule; schema-validation raises on unexpected shape; a fetch failure is loud (not a silent empty write); the app reads **both** stores from the VM's read-only API; the API exposes **no** mutation route; each store's payload carries its own freshness timestamp.

## V3-2. Durable archive (input + output)

The VM stores, durably and append-only where practical:
- **Input:** raw scraped NSE data (the backfill CSVs, live-run artifacts, VIX series).
- **Output:** model verdicts / history records (whatever currently backs the History page).

**The motivating problem:** local-only storage means a disk failure, reformat, or lost machine destroys the backfill and the verdict history — and with them, the ability to ever recalibrate cleanly. The archive is insurance against that.

Do not let a bad local write silently overwrite a good VM copy — prefer append-only/versioned storage over a blind mirror.

**GATE V3-2:** a simulated local data loss can be fully recovered from the VM archive.

## V3-3. Fail-loud monitoring + heartbeat (CONFIRMED — do not skip)

The VM runs unattended and is now the *primary* source. It therefore needs:
- **Scrape-failure alerting** — if a scheduled fetch fails, returns an unexpected schema, or starts getting blocked, the operator is alerted (email/Telegram/etc.), not left blind.
- **Resource/health checks** — disk filling from accumulating archives, memory availability (1 GB is comfortable for scrape+store, but confirm swap is configured so an unlucky spike can't OOM-kill the process).

**The Oracle idle-reclamation trap (researched, real, current for 2026):** Oracle reclaims Always Free instances that fall below roughly **15% CPU/network utilization**, and *separately* deems accounts abandoned after **30+ days with no console login**. A VM doing light periodic scraping can look "idle" by these thresholds *while working perfectly*. Two cheap preventions, both in scope:
1. A trivial **keepalive** job to keep utilization above the reclaim threshold.
2. A standing reminder (in the operations manual) to **log into the Oracle console at least monthly**.

**GATE V3-3:** an injected scrape failure produces an alert; the keepalive is running; the ops manual documents the monthly-login requirement.

## V3-4. Fallback path: trigger, visibility, and self-test

**Trigger mechanics (decided):** VM request timeout **10s**, **2 retries**, then fall back to local scraping.

**Visibility (non-negotiable, per Part I):** the fallback is **NOT silent**. When the app is running on the local fallback path, it shows a clear indicator (e.g. *"Running on local data — VM unreachable"*). The user must never be unknowingly in a degraded mode. This is the same principle as Bug #1: no indicator may misrepresent the actual state.

**Fallback self-test (decided):** a **weekly** automated check that exercises the local fallback path end-to-end (a single test scrape via the local route), logged, surfacing **only on failure**. Rationale: the fallback is code that runs rarely, and code that runs rarely rots. Without a periodic test, its breakage is discovered on the one day it's needed.

**GATE V3-4:** killing the VM causes the app to fall back to local scraping *and* display the fallback indicator; the weekly self-test runs and fails loudly if the local path is broken.

---

# PART III — BUGS (highest priority; ask → solve → confirm → next)

*These are real defects, not polish. Diagnose each properly before fixing — several are suspected to be state-sync/source-of-truth problems, and a symptom patch would leave the root cause live.*

## BUG 1 — Stale verdicts served under a fresh-looking timestamp ⚠️ **(highest priority in all of v3)**

**Symptom:** opening the app displays a "last updated / latest" timestamp that *looks* current, but the verdicts underneath are **stale**. Only the manual Refresh button or Restart Engine (in Settings) actually pulls fresh data.

**Why this is the top item:** this is not an inconvenience, it is the app **lying about its own freshness**. A user opens the app during a live IPO's close-day window, sees an updated-looking timestamp, trusts the displayed probability — and may be looking at a snapshot from *before the final QIB surge landed*. That is a stale number presented as current, at exactly the moment accuracy matters most. It is the same failure class as the decorative "Notify" bell and the persisted-but-dead toggle: **an indicator that asserts something untrue.**

**Two distinct defects to diagnose separately:**
1. **Why the on-open refresh doesn't actually trigger a real data pull.** (Does the polling cycle not fire until some later event?)
2. **Why the timestamp updates/appears fresh when no real refresh occurred.** *This must be fixed regardless of (1)* — **a freshness timestamp may only ever be written at the moment a genuine data fetch actually completes successfully.** Never on app open, never on render, never optimistically.

**GATE BUG-1:** opening the app triggers a real fetch; the timestamp reflects the last *successful* fetch and nothing else; a failed fetch does not advance the timestamp.

## BUG 2 — Alert notifications never clear (unbounded growth)

**Symptom:** alerts accumulate without limit — hundreds of entries over time.

**Retention model (operator-decided — relevance-based, not time-based):** an alert lives only while the IPO it refers to is still **actionable**. Clear:
- **Duplicate alerts for the same IPO** (keep only the latest per IPO — do not stack repeats).
- **Alerts for IPOs whose bidding window has closed.**
- **Alerts for IPOs that have moved to History / Awaiting Listing.**

This is semantically correct rather than arbitrary: once an IPO is no longer live, its alerts are dead weight.

**GATE BUG-2:** no duplicate-per-IPO alerts persist; alerts for closed/history/awaiting-listing IPOs are cleared; the alert list stays bounded over a simulated multi-IPO cycle.

## BUG 3 — Theme toggle breaks after changing theme in Settings

**Symptom:** changing theme in Settings, then using the light/dark toggle button, breaks the theme.

**Suspected root cause:** a **state-sync / two-sources-of-truth** problem — the Settings control and the toggle button both writing theme state without a shared source. This is the *same class* of bug as the notification-toggle issue already fixed (which was resolved by consolidating onto one durable store). **Diagnose whether it is the same root cause before patching the symptom** — if two paths write the same setting, unify them rather than papering over the mismatch.

**GATE BUG-3:** theme is consistent across Settings and the toggle in any order of operations; there is exactly one source of truth for the theme value.

---

# PART IV — NEW NON-MODEL FEATURES

*All display/routing only. None touches the score. Prove it (Part I, Rule 1) on every branch.*

**Data source for these:** Upstox's read-only **Analytics Token** API. **Important context:** Upstox is used here **only** for non-model convenience/context data. It was conclusively **closed as a source for subscription data** (v2 Check 1: total-only staleness, endpoint-wide, no in-API fix; and it never carried the QIB/NII/Retail split at all). It is fit for the static/reference fields below and nothing else. **Never let an Upstox field become an input to the model.**

## V3-5. RHP / DRHP direct links
Surface `rhp_url` and `drhp_url` on the IPO detail page, so the user can open the actual filed prospectus without leaving the app to hunt for it. Handle `null` honestly (not yet available → say so, don't fabricate a link).

## V3-6. Allotment tab (NEW TOP-LEVEL TAB) ⭐
A **new top-level tab alongside Live Signals / Upcoming / History**, dedicated to allotment.

**Contents:** IPOs at or past the allotment stage, each showing:
- **Registrar name** (`registrar_info.name` / `registrar`)
- **Deep-link to that registrar's own allotment-check page** (`registrar_info.website`)
- **Contact fallback** (`registrar_info.email`, `contact_number`, `contact_name`) for when something goes wrong with an application

**Hard constraint — no PAN handling.** The app **links out** to the registrar's own site; it does **not** collect, transmit, or store the user's PAN. This keeps the privacy surface at zero and matches the "your data stays on your device" posture. Do not build an in-app PAN lookup.

**Why this earns a tab:** registrars differ per IPO, and users currently have to hunt for which registrar handled which IPO and where to check. This is pure routing convenience — high value, zero risk.

## V3-7. `mandate_end_date` → verify against the T+3 close-day cutoff ⭐ (a correctness item, not display)
Upstox exposes `timeline.mandate_end_date` (the ASBA bank-mandate deadline). Our close-day cutoff logic has been using an **approximated** SEBI cutoff (flagged ◐ verify-first in the v2 deep dives — the exact minute was never confirmed against the circular).

**Task:** determine whether `mandate_end_date` (and `daily_start_time`/`daily_end_time`) is reliable enough to **replace the approximation with a sourced value**. If yes, this is a genuine correctness improvement to when the "book closed" scoring cycle fires — not cosmetic.

**Caution:** this touches *when* the engine scores, not *how*. Verify carefully, and if the sourced value would change scoring timing, treat it as a deliberate, reviewed change — not a silent swap.

## V3-8. `lot_size` fallback
NSE's `lot_size` is **often null** (a known gap, hit during A3's allotment-odds work). Use Upstox's `lot_size` as a **fallback** where the NSE value is missing. Cross-check, don't blindly overwrite: NSE remains authoritative where it has a value.

## V3-9. Subscription trend graph (DISPLAY ONLY)
Now that the VM collects subscription data at intervals, show users **how subscription built over time** — a trend graph on the detail page.

**CRITICAL BOUNDARY:** this is a **display feature only**. It is **not** a reopening of **B1 (subscription trajectory as a score feature)**, which was probed and returned a null result. Showing the curve to a human ≠ feeding the curve to the model. If trajectory-as-a-feature is ever revisited, it requires a **fresh, deliberate gate** on clean self-collected data — a separate decision, not implied by this graph.

## V3-10. Anchor investor list (context only)
Display the anchor investor list as informational context on the detail page. **Not a score input** — `anchor_quality` was deferred as a score feature (data-limited, strong QIB-redundancy prior). Showing the list to a human is a different, safe use.

## V3-11. Minor context fields
`isin` (stable identifier), `industry`, `cut_off_price`, and `status` (open/closed/listed/upcoming — usable as a **cross-check** against our own date-derived status logic, which may miss edge cases). Low effort, low risk, adds useful context.

**Explicitly DISCARDED: GMP as context.** (Operator decision.) It is not shown anywhere in v3. It remains out of the model (v2: NOT EARNED) and now also out of the UI. Note for the record: competitor apps that display GMP have drawn user accusations of showing fake/unreliable rates — a live reputational risk in this space. Not our problem, because we don't show it.

---

# PART V — COSMETIC / UI

## V3-12. Logo change
Swap in the already-designed logo. Asset replacement across app icon, installer, and in-app branding.

## V3-13. Refresh button beside the alert bell
Add a Refresh control next to the alert bell in the header, matching the one already in Settings. (Note: once **BUG 1** is fixed and the app refreshes correctly on open, this becomes a convenience rather than a necessity — but it stays, because manual refresh is still a reasonable thing to want.)

## V3-14. "Awaiting listing" outcome placement
The "awaiting listing" outcome is not correctly placed in the layout. Fix the positioning/layout so it reads coherently in the flow of the screen.

## V3-15. Readability/consistency pass
Carry forward the standards from the v2 UX polish: secondary text stays legible (size **and** contrast — small-and-faint is two problems), primary data stays prominent, hierarchy preserved. Any new v3 surface (the Allotment tab, the trend graph, the RHP links) must match the existing app's terminal aesthetic rather than introducing a new visual language.

---

# PART VI — PRIORITY ORDER

1. **BUG 1** — the stale-verdict/false-timestamp fix. First, because the app is currently misleading its user during exactly the moments that matter most.
2. **BUG 2, BUG 3** — alert retention, theme state-sync. (Ask → solve → confirm → next.)
3. **V3-1 → V3-4** — the VM data layer: ingestion, archive, monitoring, fallback + self-test. Build the fallback and its visibility indicator *in the same pass* as VM-primary — never ship VM-primary without a working, visible fallback.
4. **V3-7** — the `mandate_end_date` correctness check (it's the only v3 item that could improve accuracy, so it outranks the display features).
5. **V3-5, V3-6, V3-8, V3-9, V3-10, V3-11** — the non-model features. The Allotment tab (V3-6) is the biggest of these; the rest are small.
6. **V3-12 → V3-15** — cosmetic/UI last.

---

# PART VII — WORKFLOW (carried forward from v2, unchanged)

- **Branch-first.** All work on a branch; `main` stays green and shippable.
- **Prove the scoring path is untouched on every branch** (git-proven). This is the check that makes v3's "non-model" claim real.
- **Pause and report before every merge.** Nothing reaches `main` without operator review.
- **Ask → solve → confirm → next** for the bug work; don't batch silently.
- **Update the operations manual** (`operations/README.md`) with anything v3 adds that a future operator must know: the VM's existence and role, the monthly Oracle-console login requirement, the keepalive, how to check whether the app is on VM or fallback, and how to restore local data from the VM archive.

---

# PART VIII — PROGRESS LOG
*Maintain in `docs/v3/V3_PROGRESS.md`.*

| Date | Item | Type | Outcome | Notes |
|---|---|---|---|---|
| | | infra / bug / feature / cosmetic | built / fixed / deferred | |

---

# APPENDIX — OPEN, NOT IN SCOPE

*Recorded so they are not silently forgotten, and not silently started either.*

- **The SEBI Investment Adviser question remains OPEN and unresolved.** The app is private again, which reduces urgency but does not answer the question. Relevant 2026 development: SEBI's new **AI Accountability Framework** for advisers explicitly states that using AI *increases* rather than reduces the adviser's responsibility, and requires audit trails of model updates and disclosure of AI usage. The regulatory direction is toward more scrutiny of AI-driven financial tools, not less. **Nothing in v3 should be read as a judgment that this question is settled.** If public distribution is ever revisited, this must be resolved first — with a lawyer, not by inference.
- **Total-only model** — fully validated (statistically tied to the shipped model, survives regime/T+3 stress with a softer cold-regime ECE that the existing cold flag already handles). **Shelved, not adopted.** It exists as a ready contingency *if* public distribution is ever pursued and a licensed data source is secured. NSE/BSE-direct licensing is the standing recommendation in that scenario, since it would unlock the full split, not just total.
- **B1 (subscription trajectory as a score feature)** — probed, null result on weak external data. If the VM's clean, self-collected interval data ever accrues enough history, a **proper re-gate becomes possible for the first time**. This is a genuine future option — but it is a *deliberate, separate decision*, and it is NOT implied by shipping the trend graph (V3-9).

---

*Engineering reference, not financial advice. The system is advisory only and places no orders. A calibrated probability is an estimate, not an assurance.*
