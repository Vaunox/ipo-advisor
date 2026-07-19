# MASTER BLUEPRINT — IPO Advisor v3-DP (Forward Data Plane)

### Claude Build Handoff Document — v3-DP

*v3-DP is a **BUILD-track document**, in the lineage of v3. Like v3, and unlike v2, **nothing here touches the model** — no item enters the score, adjusts the calibrator, or changes a probability. But "it doesn't touch the model" is a claim to be **proven, not assumed**, and v3-DP carries one sharper hazard than the rest of v3: it collects the exact data a rejected model feature (B1, subscription trajectory) would want. So the invariant is not merely "off the scoring path" — it is that the collected series must be **structurally unreachable from the model**, enforced by test, so that possessing the data can never quietly become feeding it to the score. Grounded July 2026.*

---

## HOW TO USE THIS DOCUMENT

v3-DP is a **single workstream**, not a multi-part phase: one dependency chain that builds a forward subscription data plane and the display + analysis that sit on top of it. The items are ordered by dependency, which here *is* risk order, because each blocks the next. Read top to bottom; build in order.

The companion ledger — merge SHAs, live-verified vs. merged-but-unproven — lives in [`V3-DP_PROGRESS.md`](./V3-DP_PROGRESS.md), one row per item as it moves (the same convention as `V3_PROGRESS.md`).

**Standing process rule (carried from v3):** branch → gate (ruff/black/mypy-strict/pytest + scoring-path guard) → report → **pause before merge**. Diagnose-first. One writer, one home. Silent failure is the enemy. Ask on genuinely-open decisions rather than defaulting to one.

---

## WHAT v3-DP IS

A **forward point-in-time subscription data plane**: a third data plane on the VM that banks the full intraday demand-book trajectory of every mainboard IPO across its open→close window — the time-series the store has never kept.

As of the code review (`41faf33`), the store holds **`N=0`** intraday pairs: `ipo_records.parquet` is current-state (overwrites), the raw cache is one-shot, the backfill is one final row per IPO. The close-day questions this project keeps returning to — does the noon book differ from the 3 PM book, does QIB front-load late, is an early verdict safe to act on — are **unanswerable from history**, because the history was never recorded. Intraday subscription is **collect-forward-or-lose-it**; there is no free historical archive to backfill from (NSE re-serves only the final book). This plane starts the clock.

The arc has four items, ordered by dependency:

- **DP-1 — The recorder.** Bank the series. *(Anchor item; ships first and alone.)*
- **DP-2 — The read route.** Serve one IPO's series, GET-only. *(Blocked on DP-1.)*
- **DP-3 — V3-9 trend graph.** Display the curve on the detail page. *(Blocked on DP-2.)*
- **DP-4 — The close-day trajectory study.** Read-only analysis once data accrues; settles the parked #1 emission question. *(Blocked on accumulated data, ~6–12 months.)*

---

## THE INVARIANTS (govern every item)

1. **`MAX|Δprob|=0.0` by construction.** Every item is off the scoring path. Proven per item — git-proven scoring path untouched + the scoring-path guard + an import-boundary test.
2. **The B1 wall.** The series store is unreachable from `features/`, `model/`, `calibration/`. *Collecting the trajectory is not feeding it to the model.* B1 (subscription-trajectory-as-a-score-feature) was gated in v2 and **returned a null result — it is in the graveyard.** Possessing this data does **not** reopen it; that requires a fresh, deliberate v2-style gate on clean self-collected data. The import-boundary test exists precisely so a future session cannot mistake "we have the data now" for "the gate is open."
3. **Silent failure is the enemy — doubly so here.** This plane's entire value is being *complete* months from now. A store that fails invisibly looks like nothing until the day you need it and find gaps. Every item surfaces its own health where the operator will actually see it.
4. **One writer, one home.** Each store has exactly one writer; current-state and the series never mix.

---

# DP-1 — Forward subscription recorder

### One-line essence
Every 30 minutes the VM already asks NSE for the current subscription in order to score it. DP-1 makes that **same fetch also append the full reading** — permanently, in a form ready to use later — to an append-only logbook, for every IPO from the day its book opens to the day it closes. One fetch, two writes: overwrite current-state as today (Path A), append a timestamped row to the series (Path B).

### Why it exists
The store discards the trajectory the instant it scores it. To ever answer the close-day question — or draw the V3-9 curve — the trajectory has to be *banked as it happens*. There is no historical archive to backfill from. DP-1 is the instrument that turns "unanswerable from history" into "answerable, once time passes."

### The locked design (each decision with its reasoning)

**1. Piggyback the existing ingest fetch — no second call, no second timer.** The live ingest (`run_live_ingest.py` → `refresh_from_nse`) already hits NSE every 30 min, 24/7, and extracts what it needs. Path B rides that same response: after the current-state upsert, append the full reading to the series. Zero added NSE load, zero scheduling risk on the 1-vCPU box, and the recorder's cadence *is* the ingest cadence — no keepalive collision to tune.

**2. Append-only, a physically separate store, opposite write-semantics from current-state.** Current-state lives in `ipo_records.parquet` — `dict[ipo_id]`, overwrite, one row per IPO, the app's scoring input. The series lives in its own store (the retired recorder's `daywise_subscription.parquet` home — schema already correct: 11 columns incl. `source_update_time`). These must never be the same writer or file: one overwrites, one appends, and mixing them is exactly the corruption class the code review's #2/#3 criticals describe.

**3. Window gate: record from open through close.** Path B fires while `open_date ≤ today ≤ close_date` — the whole live-book window (typically three days), not just the final day. Before open there is no book; after close the number is settled. This captures the full multi-day trajectory the graph and the study both need, rather than a single-day slice.

**4. Record every 30-min cycle, unconditionally — even when the reading is unchanged.** A flat stretch is *signal* ("the book did not move 14:00→17:00"), and it is the direct evidence the close-day question needs ("no surge happened"). `captured_at` + NSE's `updateTime` on each row distinguish a genuine repeat from a stalled fetch. De-duping would silently discard the very "nothing surged" evidence the operator cares about.

**5. Carry NSE's `updateTime`, and store the raw response ready-to-use.** `NseSubscription` currently *discards* NSE's own `updateTime` (the abandoned recorder captured it as `source_update_time`); the review found it is the authoritative per-IPO provenance stamp — when that reading was actually true. DP-1 threads it through from the adapter. Per the "capture everything for the future" intent, each sample stores **every field NSE returns, extracted into typed columns, AND the complete response retained in a directly-loadable form** — ready-to-use, not a raw escaped-JSON string a future self must re-parse. Belt and suspenders: nothing lost, everything landable.

**6. Crash-safe append is a first-class requirement, not a detail.** This store is *nothing but* appends, running unattended for months, and the review's #2/#3 criticals are precisely torn-parquet corruption. The append mechanism must be designed so an interrupted write can never corrupt the accumulated series — resolved explicitly in the build's plan stage (per-IPO file, date-partitioned dataset, or an append-native format), not improvised. **The store's physical shape follows this decision** (see the coupling note below); the blueprint deliberately does not pre-commit a single-file layout.

**7. Health surfaced loudly — it must not fail silently.** Because the payoff is deferred, silent death is the cardinal risk. DP-1 wires: (a) a **new Telegram digest row** — recorder last-write time + samples-written-this-period; (b) an **immediate alert on a write failure**, so the operator can run a manual fetch (~15 min off-schedule; the manual append self-documents via its true `captured_at`, and the next auto cycle resumes on its normal mark — a failure costs one shifted sample, never a hole); (c) the same surfaced in the heartbeat/console. The manual-fetch path appends a normal row like any other.

### Coupling note (durability ↔ store shape)
Points 2 and 6 are coupled: Parquet is not naturally appendable, so the crash-safe append design partly *dictates* the physical shape (one atomically-rewritten file vs. a partitioned dataset vs. an append log). The blueprint therefore treats the exact on-disk layout as an **obligation resolved in the build plan**, not a locked choice — letting a documentation decision constrain an engineering-safety decision would be backwards. DP-2 depends on the store being *readable by `ipo_id`*, not on its layout, so leaving the shape open costs nothing downstream.

### The boundary (stated so it cannot drift)
**DP-1 collects. It does not display and does not score.** The series is written by one VM-side writer and read by nothing yet — DP-2 will add a display read; the model reads it *never*. A code comment at the store boundary records that any model use is a separate, deliberate future gate (B1), out of scope here and closed.

### Proof obligations
- **Scoring path untouched:** git-proven (0 changes under the `model/`|`features/`|`calibration/`|`core/` scoring closure) + scoring-path guard clean → `MAX|Δprob|=0.0`.
- **B1 wall:** an import-boundary test asserting the series store is unreachable from the scoring path's transitive closure — extending the existing guard that already walls off `ipo.archive` and the context store.
- **Append durability:** a test proving an interrupted/torn write cannot corrupt or truncate the accumulated series (the crash-safe mechanism verified, not assumed).
- **Honest gaps:** a failed/absent fetch appends nothing (no fabricated row), and that gap is visible in the health surface.

### Build discipline
Plan-first (read the ingest path + retired schema, report the seven-point design, **pause** — a store that runs unattended for months is the last place to guess the shape). Then branch → gate (ruff/black/mypy-strict/pytest + scoring-path guard + the new import-boundary test) → prove `MAX|Δprob|=0.0` → report → **pause before merge**. PWA untouched (engine/VM only). Deploy delta: piggyback wiring into the live-ingest unit + the new Telegram row config + a runbook update — a code+deploy change, not a new timer.

### Explicitly out of scope for DP-1
The `/subscription-series` read route (DP-2), the V3-9 graph (DP-3), the noon-vs-3PM study (DP-4), any model/feature use of the series (B1 — closed), and the parked #1 close-day emission fix (untouched, awaits DP-4).

---

# DP-2 — The subscription-series read route

### One-line essence
A fourth GET route on the VM read-API — `/subscription-series?ipo_id=…` — that serves **one IPO's** banked trajectory (the rows DP-1 appends), so the app can later draw the curve. It inherits the read-only, rate-limited, no-model guarantees the existing routes already carry; the only genuinely new design work is **volume containment**, because it is the first route serving a *time-series* rather than current-state.

### Why it exists
DP-1 banks the series to disk on the VM; nothing can read it yet. DP-2 is the one small door through which the app (in DP-3) reads a single IPO's curve. It is display-plumbing — it moves data the model already can't see out to a screen — and it is what unblocks DP-3.

### What it inherits for free (do not re-solve solved problems)
The existing read-API (`src/ipo/vm/server.py`) already establishes the pattern this route drops into:
- **Read-only, structurally.** The route is a `@app.get`. The existing `test_api_is_structurally_read_only` walks *every* route and asserts no mutating verb + a functional `POST → 405`; a new GET route is covered automatically — the guarantee extends itself.
- **Rate-limited and CORS-wrapped.** The `_FixedWindowLimiter` middleware and the CORS layer wrap all routes; the new route is bounded the moment it exists.
- **No model.** `server.py` imports only data/core layers, never the scorer; the VM still structurally cannot run the model. The series route reads the series store the same data-only way.
- **Read fresh from disk each call**, like `/records` — so a recorder write is served immediately, no caching layer to stale.

### The one new problem: volume (this is the whole of DP-2's real design)
`/records` and `/context` each return **current-state** — roughly one row per IPO, a small bounded blob. The series is the opposite: **many rows per IPO** (a sample every 30 min across ~3 days ≈ 100+ rows, growing). Two consequences the existing routes never faced:

1. **Never serve the whole store.** The route is **mandatorily scoped to one IPO** — `?ipo_id=…` required, not optional. Returning the entire series store on every call would hand a growing multi-IPO blob to a 1-vCPU/1-GB box on every detail-page open — self-inflicted box-starvation. One IPO per request is the design, not a convenience.
2. **The rate-limit arithmetic changes and must be re-checked.** The existing 60/min limit was sized for "2 requests per user per 30-min cycle." The series route adds a detail-page-open call shape. 60/min is expected to stay comfortable (you'd need 60 detail-opens/min from one IP), but the obligation is to *confirm* the DP-3 usage pattern stays under the shared limit, not assume it. If it doesn't, the fix is a per-route budget, not raising the global one (which protects `/records`).

### The envelope (consistent with the plane's one rule)
The route returns the same `{refreshed_at, data}` shape every other route uses, so freshness travels with the data. Concretely: `{refreshed_at, ipo_id, samples: [...]}` where `refreshed_at` is the **last recorder write for that IPO** (the series' own freshness — see the per-IPO note below), and `samples` is the ordered trajectory. A **shared envelope schema** in `vm/models.py` (a `SeriesEnvelope` alongside `RecordsEnvelope`/`ContextEnvelope`), validated at both ends — "don't trust a 200" enforced by parsing, as the existing envelopes are.

### Per-IPO freshness (a coupling note for DP-3)
This route's `refreshed_at` is *per-IPO*, not the app-global `last_success` that `/records` carries — because a per-IPO series has per-IPO freshness (IPO A open now, recorded 10 min ago, still growing; IPO B closed last week, complete). That is more honest, but it means DP-3's "how fresh is this curve" label reads a **per-IPO** timestamp — "updating" for an open book, "complete" for a closed one — not the single global clock every other surface uses.

### Honest degradation (match the existing routes' discipline)
- **Unknown/absent `ipo_id`** (no series banked yet — the common early case) → an **empty-but-valid** envelope (`{refreshed_at: null, ipo_id, samples: []}`), **not a 404 or 500** — exactly as `/context` returns `{refreshed_at: null, ipos: {}}` for a missing cache. For months, *most* IPOs will have no series, and that must read as "not recorded," not as a failure.
- **Missing `ipo_id` param** → a clean 4xx (the one genuine client error — a malformed request, distinct from a valid request for an IPO with no data).
- **Corrupt/unreadable series** → empty envelope + a logged warning (honest-logging discipline), never a torn read that 500s the box (the #2/#3 lesson applied to the read side).

### Proof obligations
- **Read-only:** covered by the existing all-routes test automatically; add an explicit GET-only assertion for the new route (belt-and-suspenders).
- **`MAX|Δprob|=0.0`:** VM-only, no scoring-path file touched — git-proven + guard. (This route runs only on the VM; a PyInstaller hidden import the `.exe` carries but never executes, like the rest of `vm/`.)
- **Bounded:** confirm the DP-3 usage pattern stays under the shared rate limit; test that a series response still carries `Retry-After` + CORS headers when limited (mirroring the existing limiter tests).
- **Honest empty:** test that an unknown `ipo_id` returns the empty envelope, not an error — the months-long common case.

### Build discipline
Branch → gate → report → **pause before merge**. Engine/VM only, PWA untouched (DP-3 is the frontend). Deploy delta: the new route ships in `run_vm_server.py`'s app; the operator restarts the VM server unit (the `.venv` editable install picks up the new code, no dependency change) and adds `/subscription-series` to the runbook's GET-only route list.

### Explicitly out of scope for DP-2
The graph that consumes this (DP-3), the analysis (DP-4), any model use (B1 — closed), and DP-1's internal store shape (invisible here by design — DP-2 depends on read-by-`ipo_id`, not on layout).

---

# DP-3 — Subscription trend graph (V3-9, display-only)

### One-line essence
On the IPO detail page, show **how the subscription book built over time** — a small trend curve of the QIB/NII/retail multiples across the open→close window — read from DP-2's route. It is a picture of the trajectory DP-1 banked, shown to a human. Nothing more.

### Why it exists
Today the detail page shows only the **final** subscription figures (the "Subscription (final)" card). A user sees "QIB 92×" but not *how it got there* — steady build vs. close-day surge. This is the original **V3-9**, deferred in v3 for one reason ("needs the VM to first accumulate forward interval time-series"), now unblocked by DP-1.

### THE BOUNDARY (restated in bold because it is the whole risk of this item)
**This is a display feature only. It is NOT a reopening of B1 (subscription trajectory as a score feature), which was probed in v2 and returned a null result.** Showing the curve to a human ≠ feeding the curve to the model. If trajectory-as-a-feature is ever revisited, it requires a *fresh, deliberate gate on clean self-collected data — a separate decision, not implied by this graph.* DP-3 reads the series into a chart component; the series never enters feature construction. DP-1's import-boundary test makes that structural — and it does not forbid the chart from reading the data, only the scorer.

### The design (each decision, its reasoning)

**1. It lives on the detail page, beside "Subscription (final)" — not a new tab, not a new screen.** The final-figures card answers "where did it end"; the trend answers "how did it get there." Same question at two resolutions; they belong adjacent. The graph inherits the detail page's context rather than inventing a surface.

**2. Terminal aesthetic, no new visual language.** Per V3-15's standing rule — every new v3 surface must match the existing terminal aesthetic. The curve uses the app's existing verdict/feature colors (the QIB-green already in the final card), monospace axis labels, the same card chrome. It should look like it was always there, not like a charting library was bolted on.

**3. Per-IPO freshness, from DP-2's envelope — not the app-global clock.** This curve's "last updated" is its own: "updating" for an open book, "complete" for a closed one. It reads DP-2's per-IPO `refreshed_at` and must **not** show the app's single global updated-time, which would misread a finished curve as stale.

**4. Honest empty state — whole-series absent (the History-page case).** For IPOs that closed before recording began (most of the existing History), the graph **frame renders** but the plotting field is empty, with a centered honest note *inside* the frame — "no trajectory recorded (closed before interval recording began)." It reads as *never watched*, distinct from a failure. Card, axes-frame, and terminal chrome stay present; only the line is absent.

**5. Partial gaps vs. flat stretches — for recorded IPOs.** A recorded IPO with a fetch-failure window shows the line **broken** across that span (a visible gap, **never an interpolated bridge** — the chart must not invent data DP-1 didn't record). A genuinely flat book shows a **flat line** (recorded, unchanging — that's signal). Whole-absent (point 4), partial-gap, and flat must be **three visually distinct states**, because they are three different truths: never recorded, recorded-but-missed-a-window, and recorded-and-steady.

**6. It shows the book, it does not re-score it.** The graph plots the *raw subscription multiples over time*. It does **not** compute or display a probability-over-time, a verdict-over-time, or any scored quantity derived from the trajectory — that would be re-scoring on partial books (the parked #1 hazard) and would blur the display/model line. Verdict history already exists as its own honest, separate element; DP-3 is the *input* trajectory, not a second verdict timeline.

### What it does NOT do (boundary, concrete)
- No probability-over-time, no verdict-over-time, no scored curve (point 6).
- No new tab or screen (point 1).
- No feeding the series to the model (the B1 wall).
- No touching the "Subscription (final)" card's numbers — the graph sits beside it.

### Proof obligations
- **`MAX|Δprob|=0.0`:** DP-3 is **frontend-only** (a React chart component + the DP-2 fetch) — machine-checkable as zero Python in the scoring path, as V3-1 step 3 (the fallback chip) proved itself. Plus scoring-path guard clean.
- **B1 wall holds:** the series reaches a *chart*, never a feature — covered by DP-1's import-boundary test; DP-3 adds no path from the series into `features/`.
- **Honest states tested:** empty envelope → "not recorded" (not a broken chart); a gap → a broken line (not interpolation); a flat book → a flat line — the "UI must never lie" cases, with frontend tests (`node --test`).

### Build discipline
Branch → gate (ruff/black/mypy-strict/pytest + scoring-path guard + `tsc` + `vite build` + `node --test`) → report → **pause before merge**. First DP item that ships in the **`.exe`** (PWA change): the gate proves the code, the built `.exe` proves it live — the two-stage discipline of V3-16. Preview-first is worth honoring: show the curve's look against real sample data before committing the full surface.

### Dependency & sequencing
Blocked on DP-2 (route) and beneath it DP-1 (data). DP-3 can be *built* as soon as DP-2 exists, but shows a real curve only once an IPO is recorded end-to-end — so its live proof waits for the first fully-recorded IPO. Until then it (correctly) shows the honest empty state for every existing IPO, which is the thing to verify first.

### Explicitly out of scope for DP-3
The noon-vs-3PM analysis (DP-4), any scored/probability trajectory (parked #1 / re-scoring hazard), any model use of the series (B1 — closed), and DP-2's route internals / DP-1's store shape (both invisible here).

---

# DP-4 — The close-day trajectory study (analysis, not a build)

### One-line essence
Once the recorder has banked enough real intraday history, run a **read-only offline analysis** answering the question this whole workstream circled and `N=0` could not: does the noon book differ materially from the final book, how often, and in which direction — and therefore, is the parked **#1** close-day emission concern real in practice or a rare tail. It produces **findings**, not app code.

### Why it exists, and why it is last
Every earlier attempt hit the same wall: no intraday history existed (`N=0`). DP-1 removes that wall going forward. DP-4 is the payoff — but it is *genuinely* last, because it is **blocked on accumulated data**, not engineering. Realistically ~6–12 months and ~25–40 recorded mainboard IPOs before the sample supports a non-anecdotal answer (the same order as the 358-IPO calibration set, whose per-bucket CIs are already flagged wide). Running it early would reproduce the exact error caught repeatedly in planning: a confident claim off n=1 or n=5.

### What it answers (the questions, made precise)
1. **The fill curve.** Across recorded close days, what fraction of the *final* QIB (and NII/retail) book is already in by 12:00 / 14:00 / 15:00? The direct measurement of "front-loads late" vs "done by noon" — a belief the operator's recollection *and* the `_degrade_subscription` docstring both assert, neither with evidence.
2. **The verdict-divergence count.** For each recorded IPO, run the **production scorer + real calibrator** at the noon reading and at the final book, and count: stayed-APPLY (waiting changed nothing), **crossed-into-APPLY** (the trap — a check-once-at-noon user is misled), crossed-down, and the raw Δprobability distribution (median, worst case, count moved >10 points).
3. **The actionable-window verdict.** Combine (1)+(2) with the fixed domain facts (safe apply cutoff ~15:00; NSE final publish ~19:00) to state plainly: is there any window where the book is final *and* the user can still act, or is the honest conclusion that a validated close-day verdict is inherently post-window?

### The output — findings, then a decision, then STOP
A written findings doc in the v2 gate-report style — the fill curve, the three counts, honest sample-size and CIs, and a one-line verdict: **the close-day gap is material / immaterial / inconclusive-need-more-data.** That verdict informs the parked **#1** decision (no-fix / provisional-label / heavier fix). DP-4 changes no app code — it is the evidence that lets the operator finally decide #1 with numbers instead of intuition.

### THE HARD BOUNDARY — this is where B1 lives, and it stays closed
DP-4 is the most dangerous item in v3-DP, precisely because it is where "we now have the trajectory data" meets "let's use it." Three walls, stated so a future session cannot drift:

- **DP-4 measures; it does not promote.** Running the scorer at noon vs final is *analysis of the existing model's behavior on partial inputs* — **not** fitting a new model, not adding a trajectory feature, not touching the calibrator. It reports how today's model behaves; it does not build a new one.
- **If the findings suggest trajectory has signal, that is a B1 re-gate — a separate, deliberate decision, NOT DP-4.** B1 was gated in v2 and **returned a null result on weak external data; it is in the graveyard.** The blueprint is explicit that clean self-collected interval data makes a *proper re-gate possible for the first time* — but that re-gate is a full v2-protocol exercise (walk-forward, look-ahead shuffle collapsing skill to chance, ECE/AUC across ≥3 splits, PROMOTED-or-REJECTED, the graveyard updated either way). It is **out of scope for v3-DP entirely.** DP-4 says whether that expensive re-gate is even *worth opening* — it does not open it.
- **The #1 fix, if any, is display-layer.** Any action DP-4 motivates on #1 (a provisional-book label, an abstention gate) lives in emission/display and carries the scoped proof already worked out — it does **not** feed the trajectory into the score. Re-scoring on partial books stays off the table; that is the parked #1 hazard, not a DP-4 deliverable.

### Proof obligations
- **Read-only, zero app impact:** offline analysis against the banked series + the existing scorer/calibrator; writes a findings doc, touches no shipped code → `MAX|Δprob|=0.0` trivially.
- **No leakage in the study itself:** the noon-vs-final comparison must score each reading *as-of its own timestamp* — the noon score sees only noon's book, the final score sees the final — mirroring the calibration machinery's point-in-time discipline (`is_point_in_time_safe`, as-of `build_features`), so the study doesn't feed final data into the noon score and manufacture a smaller gap than reality.
- **Honest sample size:** every finding states N, base rate, and CIs, and marks itself *inconclusive* rather than pass/fail if N is too small — as the calibration report flags the 358-IPO per-bucket CIs as wide. No rounding a small N into a confident frequency.

### Dependency & sequencing
Blocked on DP-1 accumulating real data (~6–12 months). DP-2 and DP-3 ship long before DP-4 is runnable — the graph shows the curve to a human as data trickles in; DP-4 waits until there is enough to analyze rigorously. Last in v3-DP by necessity, not choice.

### Explicitly out of scope for DP-4
Building or re-gating any model feature (B1 — a separate v2-protocol decision, closed here); any live re-scoring of partial books (parked #1 hazard); shipping the #1 fix (DP-4 *informs* it, a later task *builds* it); and the trend graph itself (DP-3, which merely displays what DP-4 rigorously studies).

---

# PRIORITY ORDER

1. **DP-1** — the recorder. First and alone; everything else is blocked on it, and it is the only time-sensitive item (it starts the collection clock).
2. **DP-2** — the read route. After DP-1 lands and the store shape is known.
3. **DP-3** — the trend graph. After DP-2; ships in the `.exe`; shows the honest empty state until the first IPO is fully recorded.
4. **DP-4** — the study. After ~6–12 months of accumulated data; produces the findings that settle the parked #1.

DP-1→DP-3 is a normal build sequence over weeks. DP-4 is a patient item measured in months of data, not days of work.

---

# CLOSED / PARKED LEDGER (so a future session inherits the boundaries intact)

- **B1 (subscription trajectory as a score feature)** — **GRAVEYARD.** Gated in v2, null result on weak external data. v3-DP collects, serves, displays, and analyzes the trajectory — it does **not** feed it to the model at any layer (enforced by the import-boundary test). A re-gate becomes *possible for the first time* once clean self-collected data accrues, but it is a **fresh, deliberate v2-protocol decision** — NOT reopened by the data existing, NOT implied by DP-3's graph, NOT performed by DP-4. "We have the data now" ≠ "the gate is open."
- **Code-review #1 (close-day partial-book emission)** — **PARKED, awaits DP-4.** The mechanism is confirmed real in code (`book_closed` is date-level; the abstention gate doesn't catch a partial book on close day), but its real-world frequency/severity is **unmeasured** (`N=0` at the time of decision). The `knack` 42-point figure demonstrates the mechanism at *some* moment; it does **not** establish the noon-vs-3PM gap. No fix ships until DP-4 measures the gap. Any eventual fix is display-layer (provisional label / abstention gate), never re-scoring on partial books.
- **Store physical shape (DP-1 point 6)** — **open by design**, resolved in DP-1's build plan; the durability decision dictates the layout, and DP-2/3/4 are insulated from it (they read by `ipo_id`).
- **DP-2/3/4 specifics** may sharpen as DP-1's data shape lands; the boundaries above hold regardless.

---

*Engineering/research reference, not financial advice. The system is advisory only and places no orders. A calibrated probability is an estimate, not an assurance. Nothing in v3-DP touches the model.*
