# v2 Progress Log

*Every candidate ends in exactly one of two states: **PROMOTED** (gated, with a fitted weight and gate evidence) or **REJECTED** (a graveyard row). Never "in the model, ungated." Track A = BUILD items (no gate). Track B = GATE items (hypotheses run through Deep Dive #A). The default expected outcome of a Track-B candidate is a logged negative — that is the discipline working, not a failure.*

| Date | Candidate | Track (A/B) | Outcome | Evidence | Notes |
|---|---|---|---|---|---|
| 2026-07-03 | A1 — day-wise subscription recorder | A | **BUILT** (GATE A1 met) | `tests/unit/test_daywise.py` (13 tests); live run banked KNACK QIB 154× then **0 on re-run** (see below) | Append-only bank keyed `(ipo_id, captured_at)`; polls `ipo-active-category` through open books, retains NSE `updateTime` + `raw_response_hash`; content-dedupes an unchanged poll. Collect-forward data for B1 (trajectory). Does **not** touch the calibrated score. |
| 2026-07-03 | B1 data-sourcing — is historical day-wise subscription already archived? (InvestorGain / IPOGyani / IPOMatrix) | B (research) | **Forward-collection required** — no gate-usable historical archive | Research note below | Confirms Deep Dive #B. No aggregator archives day-wise **category-level** subscription with intraday resolution + point-in-time provenance. IPOMatrix (operator trial): Subscription tab = **final basis-of-allotment only**; its day-wise/timewise archive is **GMP**, not subscription. Keeps A1/A2 justified; **probe B1 cheaply before heavy investment**. |

---

## GATE A1 — met (2026-07-03)

**Item:** A1 — start banking day-wise subscription now (Track A / BUILD; Deep Dive #B, Module B1).
The clock-dependent collect-forward action: official day-by-day subscription buildup isn't
archived free, so it only exists if recorded going forward. Gates B1 (subscription trajectory).

**What was built**
- `core/types.py::DaywiseSubscriptionRow` — the append-only storage-contract row (Deep Dive #B):
  `ipo_id, symbol, captured_at, qib/nii/snii/bnii/retail/total_sub, source_update_time,
  raw_response_hash`. A collect-forward record, never a scoring input.
- `data/store/daywise.py::DaywiseSubscriptionStore` — append-only Parquet bank; natural key
  `(ipo_id, captured_at)`; never overwrites an existing observation; `rows_for` reconstructs the
  curve in capture order.
- `data/sources/nse.py` — `parse_subscription_update_time` (retains NSE's own stamp verbatim) +
  `NseClient.subscription_snapshot` (one **live/uncached** poll → multiples + stamp + response
  hash). `subscription()` behaviour is unchanged (shared `_subscription_raw` helper).
- `data/ingest/daywise.py::record_daywise_subscription` — polls every **open** mainboard book,
  appends new observations, content-dedupes an unchanged poll (same `updateTime` + multiples; or
  raw-hash identity when NSE omits the stamp). Never raises; per-issue failures skip and log.
- `scripts/run_daywise_recorder.py` — one recording pass, so banking can start on a cadence NOW
  (before A2 wires it into the scheduler). Config: `storage.daywise_dir` (under gitignored
  `data_store/`, so banked observations never commit).

**GATE A1 criteria (Deep Dive #B) — all met**
- *Rows land append-only + timestamped for a live IPO* — a live pass on 2026-07-03 (Knack
  Packaging's **close day** — the high-value QIB surge) banked one row: `qib_sub 154.34×`,
  `captured_at 2026-07-03T22:32:23+05:30`, `source_update_time "Updated as on 03-Jul-2026
  19:00:00"`, `raw_response_hash b70b7b17…`. (QIB 154× matches the app's live Knack verdict —
  same official feed.)
- *A re-run produces no duplicates* — an immediate second pass banked **0** (NSE `updateTime`
  unchanged).
- *Never overwrites; idempotent on the natural key* — `test_store_append_idempotent_on_natural_key`.
- *Reconstructed curve matches the observed progression* —
  `test_reconstructed_curve_matches_progression` (ascending QIB curve, strictly-increasing
  `captured_at`).

**Tree:** ruff + black + mypy (strict, full tree, 113 files) clean; **241 tests** pass (228 prior
+ 13 new). Invariants held: advisory-only (record-only, no order path), point-in-time (honest IST
`captured_at`), calibration untouched (no scorer/calibrator change). Defensive NSE posture reused
(cookie handshake, schema-validate-fail-loud, sanity via the frozen `ge=0` row model).

**Next (per Priority Order):** A2 (wire the recorder into the scheduler cadence with the T+3
close-day cutoff) + A3 (allotment-EV layer) + A4 (T+3 dummy). B1 (trajectory) stays blocked until
this bank has accrued enough day-by-day history.

---

## Research note — do the aggregators already hold gate-usable day-wise subscription? (2026-07-03)

**Question (would have let us skip forward-collection).** Before investing further in the recorder,
we checked whether InvestorGain, IPOGyani, or IPOMatrix already archive **historical day-by-day,
category-level** subscription for past mainboard IPOs — enough to gate B1 (trajectory) directly.

**Verdict: no. Forward-collection stays required.** This confirms Deep Dive #B's premise ("official
sources publish live figures during the window, but the historical day-by-day path is not cleanly
archived… aggregator day-wise is the cheap-probe exception, never the real gate").

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
  flat post-close (20.43×). Whether the *open-window* rows show a daily total building is the one
  remaining check — even if so, it is **daily, total-only** (misses the intraday close-day QIB surge
  and the category split where B1's signal is hypothesised to live).
- Caveat: one example, and an **InvIT** (institutional-only — no retail/sNII/bNII by instrument type);
  the tab *structure* (Subscription = final, GMP = day-wise) is a platform layout, so it should hold
  for equity IPOs, worth a 30-second confirm on one.

**Why none of them can gate B1 regardless of the above.** Subscription (`qib_sub`/`nii_sub`/
`retail_sub`) is a label/backtest-critical field in the trust boundary (`ingest.official_required_fields`)
— it must be cross-checked against official NSE/BSE and **never taken from a single aggregator alone**.
So aggregator day-wise could only ever be **probe** data, and no official archive of the intraday
buildup exists to corroborate it. IPOMatrix is also, in v1's own words, a "trial-only research pull,
NOT a sanctioned ongoing source."

**Implication.** A1 (banked, merged) and A2 (forward-collection) remain the durable path to a
gate-grade trajectory dataset — category-split, intraday, official-anchored, point-in-time-honest.
But per Deep Dive #A Step 2, **probe B1 cheaply first** (e.g. IPOMatrix's daily figures, or the banked
history as it accrues): does subscription *shape/velocity* add anything beyond the final QIB multiple?
No pulse → shelve B1, and the recorder is low-priority insurance. Pulse → forward-collection is
justified. A2's scope (standalone always-on cloud recorder) is **parked** on branch
`a2-daywise-cloud-recorder` pending this decision.
