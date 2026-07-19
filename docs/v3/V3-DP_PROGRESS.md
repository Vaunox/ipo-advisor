# v3-DP PROGRESS LOG

*Maintained per `docs/v3/MASTER_BLUEPRINT_v3-DP.md`. One row per item as it moves; newest first. Statuses distinguish **not-started** from **merged-but-not-yet-live-proven** from **live-verified**, and carry the merge `<sha>` once landed (the same convention as `V3_PROGRESS.md`). The forward data plane is a **collection-first** workstream: several items only become *live-proven* after real data accrues (a recorded IPO for DP-1/DP-3; ~6–12 months for DP-4), so "merged + gated" and "live-proven" are deliberately separate columns here.*

> **v3-DP status:** workstream **OPEN**. DP-1 (recorder) is the anchor and the only time-sensitive item — it starts the collection clock. DP-2→DP-3 follow as a normal build sequence; DP-4 is a patient analysis item gated on accumulated data. The B1 wall (trajectory data reaches display + analysis, never the model) is enforced at every layer by the import-boundary test.

| Date | Item | Type | Status | Notes |
|---|---|---|---|---|
| — | **DP-1 — forward subscription recorder** | infra (collection) | **NOT STARTED** — plan-first task drafted, awaiting kickoff | Piggybacks the live-ingest fetch; appends the full demand book + NSE `updateTime` + ready-to-use raw response to an append-only series store, open→close window, every 30-min cycle. Crash-safe append + store shape resolved in the build plan (coupling note). Health via a new Telegram digest row + failure alert. `MAX\|Δprob\|=0.0` by construction + import-boundary test (B1 wall). Live-proof waits for the first fully-recorded IPO. |
| — | **DP-2 — `/subscription-series` read route** | infra (VM) | **NOT STARTED** — blocked on DP-1 | Fourth GET route, one-IPO-scoped (mandatory `?ipo_id=`), `{refreshed_at, ipo_id, samples}` envelope with **per-IPO** freshness. Inherits read-only/rate-limit/no-model proofs; only new work is volume containment + re-checking the shared 60/min limit against DP-3 usage. Honest empty envelope for the (months-long) common case of an IPO with no series. |
| — | **DP-3 — subscription trend graph (V3-9)** | feature (display) | **NOT STARTED** — blocked on DP-2 | The deferred V3-9, now unblocked. Detail-page curve beside "Subscription (final)", terminal aesthetic, per-IPO freshness. **Three distinct honest states:** whole-series-absent (framed empty field — the History-page case), partial-gap (broken line, never interpolated), flat (flat line = signal). Shows the raw book, never a scored/probability-over-time curve (parked #1 / B1). Frontend-only → `MAX\|Δprob\|=0.0`; ships in the `.exe`. |
| — | **DP-4 — close-day trajectory study** | analysis (read-only) | **NOT STARTED** — blocked on accumulated data (~6–12 mo) | Offline study: QIB fill curve by hour + noon-vs-final verdict-divergence counts (stayed-APPLY / crossed-into-APPLY / crossed-down) + the actionable-window verdict. Uses the production scorer/calibrator as-of each reading's own timestamp (no leakage). Produces **findings** that settle the parked #1 — changes no app code. **Measures, does not promote:** a positive result is a *B1 re-gate trigger*, a separate v2-protocol decision, NOT performed here. |

---

## CLOSED / PARKED (carried from the blueprint ledger)

- **B1 (trajectory-as-a-score-feature)** — graveyard; re-gate is a separate deliberate v2 decision, not reopened by v3-DP.
- **Code-review #1 (close-day emission)** — parked, awaits DP-4's measurement; any fix is display-layer, never re-scoring on partial books.
- **DP-1 store physical shape** — open by design, resolved in DP-1's build plan.
