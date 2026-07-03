# v2 Progress Log

*Every candidate ends in exactly one of two states: **PROMOTED** (gated, with a fitted weight and gate evidence) or **REJECTED** (a graveyard row). Never "in the model, ungated." Track A = BUILD items (no gate). Track B = GATE items (hypotheses run through Deep Dive #A). The default expected outcome of a Track-B candidate is a logged negative — that is the discipline working, not a failure.*

| Date | Candidate | Track (A/B) | Outcome | Evidence | Notes |
|---|---|---|---|---|---|
| 2026-07-03 | A1 — day-wise subscription recorder | A | **BUILT** (GATE A1 met) | `tests/unit/test_daywise.py` (13 tests); live run banked KNACK QIB 154× then **0 on re-run** (see below) | Append-only bank keyed `(ipo_id, captured_at)`; polls `ipo-active-category` through open books, retains NSE `updateTime` + `raw_response_hash`; content-dedupes an unchanged poll. Collect-forward data for B1 (trajectory). Does **not** touch the calibrated score. |

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
