# v2 Progress Log

*Every candidate ends in exactly one of two states: **PROMOTED** (gated, with a fitted weight and gate evidence) or **REJECTED** (a graveyard row). Never "in the model, ungated." Track A = BUILD items (no gate). Track B = GATE items (hypotheses run through Deep Dive #A). The default expected outcome of a Track-B candidate is a logged negative — that is the discipline working, not a failure.*

| Date | Candidate | Track (A/B) | Outcome | Evidence | Notes |
|---|---|---|---|---|---|
| 2026-07-04 | A3 — retail allotment-odds estimate (P(allotment) only) | A | **BUILT** (display-only; no calibration impact) | `tests/unit/test_allotment.py` + `test_api.py`; [A3_ALLOTMENT_ODDS.md](A3_ALLOTMENT_ODDS.md) | Shows est. P(1-lot retail allotment) `= min(1, 1/retail_sub)` next to the verdict, in a **separate code path** (scorer/calibrator untouched). Honest back-check: proxy **under-states** actual by ~1.7× — **labelled an estimate, not tuned**. Scoped down from the full EV layer (gain-magnitude + opportunity-cost dropped). |
| 2026-07-04 | B2 — India VIX flag-enrichment (safe half) | B (annotation) | **BUILT** — weight 0, byte-equality proven | `tests/integration/test_vix_flag_wiring.py` + `tests/unit/test_vix.py`; [B2_VIX_FLAG.md](B2_VIX_FLAG.md) | Blends India VIX into the cold-market flag (`market_regime`, weight 0) — annotation-only; OOS probabilities **byte-for-byte identical** (proven). `vix.csv` from Yahoo `^INDIAVIX` (2008→2026). **Add-only** blend: on the backfill 59→61 cold flags (VIX +2 / −0) — only tightens, never loosens. The **score-feature** half (gated) is separate/deferred. |
| 2026-07-03 | **STANDING RULE** — live/forward data-recording jobs deferred | — | **DEFERRED (standing)** | Master blueprint **Part I-A** | Operator runs no standing/daily recorders → **A1** (removed), **A2** (cancelled), **B1**, **B4**, **B5**, and the **GMP recorder** are deferred (not rejected). NOT affected: the app's `live.py` in-session refresh; A4 occasional rituals. Lift when the operator opts to run a recorder. |
| 2026-07-03 | B1 subscription trajectory (via the A1 day-wise recorder) | B / A | **NOT PURSUED** — A1 built (GATE A1 met) then **removed** (reverted) | Removal + research notes below | No gate-usable historical day-wise subscription exists (every source is final-only or GMP-only), so forward-collection was the *only* path to gate B1 — and it was judged not worth pursuing now. A1 (`40e9230`) reverted. The app's live-verdict ingestion (`data/ingest/live.py`) is untouched. |

---

## Standing decision — live/forward data-recording jobs are DEFERRED (2026-07-03)

The operator is **not running standing scheduled or daily data-recording jobs**, so every v2 item
that depends on **collecting data forward over time** is **deferred** — not rejected on the merits,
deferred on operational choice. Full rule + rationale: **Part I-A** of the master blueprint.

- **Deferred:** **A1** (day-wise subscription recorder — removed), **A2** (live subscription
  auto-ingestion as a standing job — cancelled; the app's in-session refresh already covers live
  verdicts), **B1** (subscription trajectory — needs A1's history), and the **GMP recorder** +
  everything on it: **B4** (GMP cold re-test), **B5** (multi-source GMP confidence / spike-collapse).
- **Not affected (stay):** the shipped app's own `live.py` ingestion (in-session refresh, **not** a
  standing recorder); **A4** occasional rituals (quarterly recalibration, verdict-accuracy
  monitoring — run periodically by the operator, not daily jobs).
- **Still actionable (no recording dependency):** **A3** (allotment-EV), **B2** (VIX), **B3** (cheap
  adds), **B6** (RHP kill-flags/context), **B9** (graded regime tiers), **B7** (TabPFN), **B8**
  (conformal), **A4** (ops hardening).
- **To lift:** the operator opts to run a recorder (a local scheduled task or an always-on service)
  → the relevant deferred items become actionable again.

---

## A1 removed / B1 (subscription trajectory) not pursued (2026-07-03)

**Decision.** The A1 day-wise subscription recorder was built (append-only bank, GATE A1 met,
verified live on Knack Packaging's close day) and then **removed** — the A1 commit (`40e9230`) was
reverted. **A2** (the standalone always-on cloud recorder that would have run A1's collection
forward) is **dropped** — it was only ever uncommitted WIP and was never built. **B1 (subscription
trajectory) is not being pursued.** The research below established that the only route to a
gate-grade trajectory dataset is *forward-collection* (no free historical day-wise, category-level
archive exists), and that whole line of work (A1 + A2) was judged not worthwhile now.

**What the revert removed.** `data/ingest/daywise.py`, `data/store/daywise.py`,
`scripts/run_daywise_recorder.py`, `tests/unit/test_daywise.py`, the `DaywiseSubscriptionRow` type
(`core/types.py`), the `nse.py` snapshot helpers (`subscription_snapshot`,
`parse_subscription_update_time`, the `_subscription_raw` split), and the `storage.daywise_dir`
config. The `gate-a1` tag and the unmerged `a2-daywise-cloud-recorder` WIP branch were deleted.

**Untouched.** The shipped engine, scorer, and calibrator (no scoring path changed). The app's own
live-verdict ingestion — `data/ingest/live.py` (`refresh_from_nse`) — was always separate from the
recorder and is unaffected; the revert restores the pre-A1 `nse.py` that `live.py` already used.

---

## Research note — do the aggregators already hold gate-usable day-wise subscription? (2026-07-03)

*Retained as the record of why B1 was not pursued. If trajectory is ever revisited, start here.*

**Question (would have let us skip forward-collection).** We checked whether InvestorGain, IPOGyani,
or IPOMatrix already archive **historical day-by-day, category-level** subscription for past
mainboard IPOs — enough to gate B1 (trajectory) directly.

**Verdict: no.** This confirms Deep Dive #B's premise ("official sources publish live figures during
the window, but the historical day-by-day path is not cleanly archived… aggregator day-wise is the
cheap-probe exception, never the real gate").

| Source | Historical day-wise, category-level subscription? | Verdict |
|---|---|---|
| **IPOGyani** | Past IPOs collapse to **total only** (e.g. Knack Packaging → just `83.33×`; no category, no daily). Category/day-wise is a live-window feature only. | **(c) Not usable** |
| **InvestorGain** | Historical report = **final per-category** (one row/IPO, sortable by final QIB); no day-by-day archive. Cloudflare/JS → brittle to extract. | **(b) Probe-only** (thin) |
| **IPOMatrix** (Chittorgarh, paid) | **Subscription tab = final basis-of-allotment only.** Its day-by-day / timewise archive is **GMP** (+ price), not subscription. | **(b) Probe-only** (strongest, but not day-wise subscription) |

**IPOMatrix — direct evidence (operator's free-trial screenshots, InvIT *Citius Transnet*, 2862).**
- **Subscription tab** shows the **final** basis of allotment, category-wise — QIB(Total) 9.97×,
  Anchor 1.00×, QIB(Ex-Anchor) 23.43×, NII 16.65×, Total 11.64× — **no Day 1/2/3 buildup**.
- **GMP tab** *does* keep a day-by-day (21-day) trend with a **"Timewise History"** button and
  per-reading timestamps — i.e. IPOMatrix archives day-wise **GMP** (as the v1 GMP gate used), **not
  day-wise subscription**. Each GMP-day row carries only a **total-only** "Subscription" annotation,
  flat post-close (20.43×). Even if the *open-window* rows show a daily total building, it is
  **daily, total-only** (misses the intraday close-day QIB surge and the category split where B1's
  signal is hypothesised to live).
- Caveat: one example, and an **InvIT** (institutional-only — no retail/sNII/bNII by instrument type);
  the tab *structure* (Subscription = final, GMP = day-wise) is a platform layout, so it should hold
  for equity IPOs.

**Why none of them could gate B1 regardless.** Subscription (`qib_sub`/`nii_sub`/`retail_sub`) is a
label/backtest-critical field in the trust boundary (`ingest.official_required_fields`) — it must be
cross-checked against official NSE/BSE and **never taken from a single aggregator alone**. So
aggregator day-wise could only ever be **probe** data, and no official archive of the intraday
buildup exists to corroborate it. IPOMatrix is also, in v1's own words, a "trial-only research pull,
NOT a sanctioned ongoing source."

**Outcome.** Forward-collection was the only path to a gate-grade trajectory dataset. Rather than
build and run that collection, the decision was to **not pursue B1** — A1 was removed (reverted) and
A2 was dropped without ever being committed. The finding stands as the honest record of why.

*(A2 remains listed as a candidate in the master blueprint spec — this log records it as dropped, the
way the graveyard records rejected features; the spec is the menu, this is the outcome.)*
