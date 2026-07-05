# v2 Progress Log

*Every candidate ends in exactly one of two states: **PROMOTED** (gated, with a fitted weight and gate evidence) or **REJECTED** (a graveyard row). Never "in the model, ungated." Track A = BUILD items (no gate). Track B = GATE items (hypotheses run through Deep Dive #A). The default expected outcome of a Track-B candidate is a logged negative — that is the discipline working, not a failure.*

| Date | Candidate | Track (A/B) | Outcome | Evidence | Notes |
|---|---|---|---|---|---|
| 2026-07-05 | B1 — subscription-trajectory **cheap probe** (does the buildup SHAPE add signal?) | B (probe) | **PROBE-INCONCLUSIVE — free-data route CLOSED with evidence; NOT a permanent closure (a real gate needs forward collection)** | [B1_PROBE.md](../B1_PROBE.md); `research/run_b1_probe.py` | The last open v2 candidate, probed (Step 2 only — probe-grade data, **no build, no wiring**). Tested the new fact that the arXiv 2412.16174 HF set (`sohomghosh/Indian_IPO_datasets`, Chittorgarh) carries day-wise per-category subscription for ~418 mainboard IPOs. **Trust-check finding (for the record — saves anyone re-checking this dataset):** the HF/Chittorgarh **finals are faithful** (`Total_subscriptions` **98%** vs our NSE finals) **but the day-wise columns truncate at day 2** — the close-day QIB surge is missing — so this dataset is **endpoint-reliable, path-useless** (its day-wise reaches our verified final on only **0.8%** of the 121-IPO 2017–2023 overlap; e.g. Indigo Paints our QIB **189.6×** vs their last day **5.4×**). The clean cheap-probe route **does not exist** → (c) data too poor. **Salvage** (their day-2 + our verified final → final-day QIB surge share, point-in-time at close, **N=120**, full gate harness — fixed prior weight 0.10, calibrator refit per arm, 3 walk-forward splits, bootstrap CI): **NO PULSE** — lift ≈0 all splits (**−0.012 / −0.007 / +0.001**, CIs straddle zero), ECE worse on all 3 — consistent with **QIB-redundancy**, but on probe-grade-squared data **not a permanent closure**. **B1's honest state: neither rejected nor open — unreachable without collection, and the best free look found nothing.** A real B1 gate **requires forward collection (recorder)**; no cheap positive signal exists to chase. Read-only: **scorer + calibrator + shipped dataset byte-for-byte untouched;** probe quarantined in `research/` (`pandas` is a research-only dep, mypy-overridden like `tabpfn`). Forward-collection decision stays open (operator's). |
| 2026-07-04 | B7 — model-architecture bake-off: **TabPFN v2 vs the logistic core** | B (gate) | **LOGISTIC STAYS — question CLOSED with evidence** | [B7_BAKEOFF.md](../B7_BAKEOFF.md); `research/run_b7_bakeoff.py` | Ran **TabPFN v2** (`ModelVersion.V2`, ungated public `Prior-Labs/TabPFN-v2-clf` weights) against the shipped fixed-weight-scorer→Platt core through the **same walk-forward OOS gate** on **358** IPOs — same 3 splits, same features (QIB/NII/retail), AUC+ECE with paired-bootstrap CI on the AUC diff. **Higher bar** (adopting TabPFN forfeits the grounded reason → must win *decisively*, not on a tie): **not met.** AUC edge tiny and within noise — **+0.004 / +0.009 / +0.018**, **every 95% CI includes zero**, none reaches the +0.03 bar; and **ECE is worse for TabPFN on all 3 splits** (0.055/0.103, 0.060/0.093, 0.060/0.080) — worse-calibrated, which matters for a *calibrated-probability* product. Confirms the prior: on a simple QIB-led signal a flexible transformer finds nothing the fixed weights miss. **Interpretability + operational cost** (opaque ~29 MB/torch dependency + vendor telemetry; the newer TabPFN line v2.5/v2.6/v3 is license/account-gated) only *raise* the bar. Deterministic (`random_state=0`, bootstrap `seed=17`); re-ran byte-identical. **No `src/` change; scorer + calibrator byte-for-byte untouched;** bake-off quarantined in `research/` (excluded from build). The **expected, acceptable** outcome — the discipline working. |
| 2026-07-04 | B2 (second half) — India VIX as a **score feature** | B (gate) | **CUT — NOT EARNED** (the weight-0 flag half stays shipped) | [B2_SCORE_GATE.md](../B2_SCORE_GATE.md); `research/run_b2_gate.py` | Gated the VIX **score-feature** half (the flag-enrichment half shipped weight-0 earlier) on the expanded **358** sample: fixed prior weight (0.10, a-priori sign high-VIX→lower), calibrator refit per arm, 3 walk-forward splits, bootstrap CI. **CUT** — AUC lift ≈0 (CI straddles zero on **every** split) and **ECE worsens on all 3 splits** (0.055→0.058, 0.060→0.074, 0.060→0.068) → **QIB-redundant**: fear already echoes through cautious QIB bidding, exactly the blueprint's prior. The bigger, cold-market-inclusive sample (2018–19 / 2020) gave it a fairer shot and it still earned no weight. **No `src/` change; calibrator byte-for-byte untouched;** the shipped VIX cold-flag (weight 0, B2 first half) is unaffected. |
| 2026-07-04 | B8 Idea 1 — conformal uncertainty bands | B (built, not shipped) | **NOT PURSUED** — built + coverage-validated on a branch, chose not to ship | [B8_CONFORMAL.md](../B8_CONFORMAL.md); git tag `b8-conformal-shelved` | **B8 Idea 1 (conformal bands) — built and coverage-validated on the branch, chose not to ship. The cold flag (B9/B2) already delivers the actionable uncertainty message; the bands were a quantitative refinement not worth the rework. Idea 2 (regime-aware) remains deferred. Not pursued.** Rate-coverage **80%→80%**, **MAX \|Δprob\| = 0.0** (estimate band; the outcome-vs-estimate-band fork is recorded in the report). **Main untouched** — the shipped scorer, calibrator, frontend, and cold flag are all exactly as they were; B8 never merged. Full code (module + wiring + tests) preserved off-main under git tag **`b8-conformal-shelved`**. |
| 2026-07-04 | Dataset expansion — backfill **293 → 358** (extend to 2017) + 1 data correction + recalibration | A (data) | **BUILT — gate RE-PASSED, no regression** *(merged; tag `data-2017-extend`)* | [CALIBRATION.md](CALIBRATION.md); `models/{calibrator,reliability}.json`; `data/backfill/mainboard_ipos.csv` | Added **65 validated pre-2021 mainboard IPOs (2017–2020)**, **two-source cross-checked before trusting** (NSE vs Kaggle: QIB/NII/retail 98%, listing price + band 100%; concrete exact matches — CDSL, Dixon, Cochin Shipyard). Corrected **1 confirmed data error**: Electronics Mart QIB **62.28 → 169.54** (third-source verified: ipowatch/5paisa/chittorgarh). **Gate RE-PASSED** on 358 (AUC 0.797, ECE 0.081, APPLY-precision 0.848 — all within bounds); new calibrator reproduces (Δ 0.0). **No regression:** recalibration flips only **1** verdict of 386 (max Δprob 0.042), and recent-period calibration **improved** (late ECE 0.056 vs 0.073). OOS 233 → 298. **Pre-2017 (2010–16) correctly rejected** — aggregator-single-source, fails the two-source rule. **Cold-market bonus (for later):** the +65 add genuine cold-regime IPOs (2018–19 weakness, 2020 COVID) with labels + subscription — a **partial un-block** of the cold-data those items were waiting on: directly helps **B8 Idea 2** (regime-aware calibration now has some cold OOS outcomes) and enlarges the cold slice for **B4** (though B4 still additionally needs cold-market GMP from the recorder). Bucketed issue-size re-test still ~293 (pre-2021 has no issue-size without a Chittorgarh fetch). |
| 2026-07-04 | B6 — RHP mandated-disclosure extraction → detail-page context (Option B) | B (probe) | **NOT VIABLE** — display not wired; extractor dropped from `src/`, kept as evidence | [B6_RHP_PROBE.md](../B6_RHP_PROBE.md); `research/rhp_extract.py` + `research/rhp_probe.py` | Probed extraction of the SEBI-mandated *Summary of Outstanding Litigation* over 100 HF prospectuses **before wiring any display** (probe-before-build). **Section detected 81%, but structured litigation count/amount extracted only 6/100 (~7% recall).** Root cause is a **data ceiling** — OCR'd scanned PDFs with reflowed/garbled mandated tables, not a fixable regex. **Precision high & safe:** 0 fabricated of 6 (Vedant 22/₹240.53mn, Delhivery 89/₹411.69mn exact; the parser **abstains rather than guesses** — validates the never-invent safeguard). **Related-party 100/100 = constant** → zero discrimination (a "don't bother", cf. B3's structural findings). Auditor opinion 54% (mostly benign emphasis-of-matter) — not worth frontend plumbing. **No scoring/frontend change; calibrator byte-for-byte untouched.** |
| 2026-07-04 | A4 — operate-phase hardening (monitoring · T+3 stability · housekeeping · heartbeat · recalibration check) | A | **BUILT** — GATE A4 met (3/3 clauses); no scoring path touched | `tests/unit/{test_monitoring,test_stability,test_heartbeat,test_calendar}.py`; `scripts/run_{accuracy_monitor,t3_stability,heartbeat,recalibration_check}.py`; [T3_STABILITY.md](../T3_STABILITY.md) | Five operator-run rituals/tools; **calibrator byte-for-byte untouched**. (1) **Drift monitor** — recent-window APPLY precision/ECE vs the walk-forward OOS baseline; alerts only on a *real* departure (recent Wilson-CI entirely below baseline). (2) **T+3 stability** — cross-break calibration report: **STABLE** (pre n=52 ECE 0.098 / post n=181 ECE 0.089, shift −0.009; CIs overlap). (3) **Housekeeping** — NSE 2026 holidays completed from the official circular (**fixed Holi 03-17→03-03**, a lunar-guess error), `latest_covered_year`/`review_due` staleness guard, httpx `<1.0` pin + warning-clean suite. (4) **Heartbeat** — feed freshness (flagged Nifty 15d stale, calendar needs 2027). (5) **Recalibration reproduces** the shipped calibrator (max Δ 0.0, GATE A4 clause 2). +28 tests → 269. |
| 2026-07-04 | A3 — retail allotment-odds estimate (P(allotment) only) | A | **BUILT** (display-only; no calibration impact) | `tests/unit/test_allotment.py` + `test_api.py`; [A3_ALLOTMENT_ODDS.md](A3_ALLOTMENT_ODDS.md) | Shows est. P(1-lot retail allotment) `= min(1, 1/retail_sub)` next to the verdict, in a **separate code path** (scorer/calibrator untouched). Honest back-check: proxy **under-states** actual by ~1.7× — **labelled an estimate, not tuned**. Scoped down from the full EV layer (gain-magnitude + opportunity-cost dropped). |
| 2026-07-04 | B2 — India VIX flag-enrichment (safe half) | B (annotation) | **BUILT** — weight 0, byte-equality proven | `tests/integration/test_vix_flag_wiring.py` + `tests/unit/test_vix.py`; [B2_VIX_FLAG.md](B2_VIX_FLAG.md) | Blends India VIX into the cold-market flag (`market_regime`, weight 0) — annotation-only; OOS probabilities **byte-for-byte identical** (proven). `vix.csv` from Yahoo `^INDIAVIX` (2008→2026). **Add-only** blend: on the backfill 59→61 cold flags (VIX +2 / −0) — only tightens, never loosens. The **score-feature** half (gated) is separate/deferred. |
| 2026-07-04 | B9 — graded regime-flag tiers (normal/soft/cold) | B (annotation) | **BUILT** — weight 0, byte-equality proven | `tests/unit/test_regime_tiers.py` + `tests/integration/test_regime_tiers_wiring.py`; [B9_REGIME_TIERS.md](B9_REGIME_TIERS.md) | Binary cold flag → normal/soft/cold tiers (untuned boundaries soft −0.15 / cold −0.3), each its own caveat. Annotation-only: **MAX \|Δprob\| = 0.0** proven, each tier populated. Backfill: 239 normal / **13 soft** (new gentle caveat) / 59 cold (unchanged). No new data, no gate. |
| 2026-07-04 | B3 — cheap feature adds: NII split, issue size, pricing-vs-band, BRLM | B (gate) | **4 × NOT EARNED** — all shelved (graveyard, Part III) | [B3_GATE.md](../B3_GATE.md); `research/run_b3_gate.py` + `gate_b3_deferred.py` | Full gate per feature (with-vs-without, calibrator refit per arm, ≥3 splits, bootstrap CI); all QIB-redundant. **Structural finding:** 292/293 mainboard IPOs price at the band top → the cut-off-underpricing channel doesn't exist (closes that whole idea category). **Methodology check:** the leakage-safe point-in-time BRLM league table produced **no fake lift** (cf. GMP's leaked +0.133) → the negatives are trustworthy real nulls. Deferred data was **recovered + gated**, not left data-limited. **No `src/` change; calibrator byte-for-byte untouched.** |
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
- **Built / gated so far (no recording dependency):** **A3** (allotment odds), **B2** (VIX safe
  half), **B9** (graded regime tiers), **A4** (ops hardening) — all built; **B3** (cheap adds) gated →
  all shelved.
- **Resolved since (no recording dependency):** **B6** (RHP context — probed, not viable), **B7**
  (TabPFN bake-off — gated, logistic stays), **B8** (conformal bands — built, not shipped). No
  non-recording-dependent v2 items remain open.
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
