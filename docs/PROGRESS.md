# Progress Log — IPO Listing-Gains Advisor

Updated at the end of every phase (MASTER_BLUEPRINT Part V). The committed tree is
green (lint + types + tests) at every phase commit.

| Date | Phase | Status | Commit / tag | Tests | Notes / decisions / follow-ups |
|---|---|---|---|---|---|
| 2026-06-29 | P0 | ☑ done | `feat(p0): foundation & scaffolding` / `gate-0-foundation` | 38 passing | Foundation built; GATE 0 met. See details below. |
| 2026-06-29 | P1 | ☑ done | `feat(p1): official ingestion + labels` / `gate-1-ingest` | 78 passing | Ingestion + labels; GATE 1 met. Sample feasibility confirmed; two DD#1 decisions made. |
| 2026-06-29 | P2 | ☑ done | `feat(p2): feature layer + point-in-time correctness` / `gate-2-features` | 105 passing | Point-in-time features + leakage suite; GATE 2 met. |
| 2026-06-29 | P3 | ☑ done | `feat(p3): scoring core` / `gate-3-scoring` | 132 passing | Scorer/killflags/verdict/reason; GATE 3 met. Calibrator = marked placeholder. |
| 2026-06-29 | P4 | ☑ done | `feat(p4): backtest + calibration` / `gate-4-calibration` | 154 passing | **Reliability gate PASSED** on 311 official NSE IPOs. AUC 0.81, ECE 0.073, look-ahead 0.47. |
| 2026-06-29 | P4+ | ☑ done | `test(p4): benchmark...` | 158 passing | Model **ties** equal-selectivity QIB rule (83.7% vs 84.3%); value = calibration, not precision. |
| 2026-06-29 | P5 | ◐ framework | `feat(p5): GMP framework + re-calibration gate` | 168 passing | GMP machinery + gate built & validated (keeps informative, rejects noise). **Historical GMP data deferred** (operator decision); `gate-5` runs when sourced. |
| 2026-06-30 | P5+ | ◐ gate run | `test(p5): GMP gate on real IPOMatrix GMP` | 174 passing | **Real gate RAN** on 99 point-in-time 2025-26 IPOs (IPOMatrix trial). **GMP NOT earned** — clean as-of-close AUC lift ~0 (leaky +0.133 collapsed); keep/cut flips with split. Official-only ships; recorder keeps banking (esp. cold). See [GMP_GATE.md](GMP_GATE.md). |
| 2026-06-30 | P6 | ☑ done | `feat(p6-s6): service composition root + GATE 6` / `gate-6-service` | 197 passing | **GATE 6 PASSED** — advisory service (engine/API/scheduler/notify) composed; all five invariants survive end-to-end. Cold flag now LIVE (prereqs #1/#2 resolved); live GMP stays None. |
| | P7 | ☐ todo | | | Windows `.exe` native shell (APK deferred). |
| | P8 | — | | | Operate & maintain (ongoing). |

**Gate status:** 0 ☑ · 1 ☑ · 2 ☑ · 3 ☑ · 4 ☑ · 5 ☐ · 6 ☑ · 7 ☐

---

## Phase 0 — Foundation & scaffolding (done)

**Goal:** skeleton, config/secrets, logging, NSE calendar, core contracts.

### Deliverables built
- **Repo structure** per Blueprint Part I (`src/ipo/{core,data,features,model,calibration,service,apps}`, `config/`, `tests/`, `scripts/`, `data_store/`).
- **Tooling:** `pyproject.toml` (deps + ruff/black/mypy/pytest config, `src` layout), `.pre-commit-config.yaml`, `.gitignore`, `.github/workflows/ci.yml` (lint → format-check → mypy → pytest).
- **`core/config.py`** — layered loader: `default.yaml` + `sources.yaml` ← `env/<env>.yaml` ← `IPO_*` env vars ← explicit overrides; validated into a frozen typed `AppConfig`.
- **`core/secrets.py`** — `SecretProvider` reading env vars then an optional gitignored `secrets/` dir; `require()` raises `MissingSecretError` without leaking the value. No secret ever enters code or config.
- **`core/logging.py`** — structured JSON logging, IST timestamps, idempotent `configure_logging`, structured `extra` promotion.
- **`core/calendar.py`** — NSE trading-day calendar + IST clock (`now_ist`, `is_trading_day`, `next/previous_trading_day`, `trading_days_between`); holidays maintained in `core/constants.py`.
- **`core/constants.py`** — structural constants (IST tz, NSE session times, GMP cadence, NSE holiday set 2024–2026).
- **`core/types.py`** — `IPORecord`, `IPOFeatures`, `PartialRecord`, `RawResponse`, `ListingLabel`, `AnchorAllotment`, `Verdict`, and the `Segment` / `VerdictType` enums. All pydantic, frozen, `extra="forbid"`, validating at construction. `IPORecord.issue_price` = price-band top (Deep Dive #1 convention).
- **`core/interfaces.py`** — `DataSource`, `Repository`, `ScoringModel`, `Calibrator`, `Notifier` Protocols (`@runtime_checkable`). None exposes an order-placement method (advisory only).

### GATE 0 — met
- **Config loads & merges by env:** `tests/unit/test_config.py` proves dev→DEBUG, prod→WARNING, env-var override precedence, explicit-override precedence, scalar coercion, and that invalid/unknown values raise.
- **A fake of each Protocol type-checks:** `tests/unit/test_protocols.py` has a fake for each Protocol annotated as the Protocol type (mypy-verified, strict) plus runtime `isinstance` checks.
- **CI green:** locally `ruff check`, `black --check`, `mypy` (strict), and `pytest` (38 tests) all pass; the same steps run in `.github/workflows/ci.yml`.

### Decisions
- **pydantic v2** for all models and config validation (consistent with FastAPI in Phase 6; validates at boundaries per Ground Rule 7).
- **`src` layout**, pytest `pythonpath=["src"]`; package is also pip-installable for later packaging phases.
- **`tzdata`** added as a runtime dependency — `zoneinfo` has no system tz database on Windows (the target `.exe` platform).
- **`logging.json` YAML key** is aliased to the Python field `json_output` to avoid colliding with `BaseModel.json`.
- NSE holiday set is hard-coded structural data in `core/constants.py` with an explicit annual-maintenance note (2026 entries provisional).

### Follow-ups for later phases
- **Phase 1 open item (resolved):** see Phase 1 below — the ≥100-IPO sample is confirmed assemblable.
- History-depth and aggregator-trust open questions from Deep Dive #1 — settled in Phase 1 (below).

---

## Phase 1 — Official ingestion + labels (done)

**Goal:** clean, mainboard-tagged IPO records + listing-day labels, reproducible and incremental.

### Sample feasibility (Phase-4 prerequisite) — CONFIRMED
Mainboard IPO counts (NSE/BSE): 2021=63, 2022=40, 2023=57, 2024=93, 2025=104 → **~357 since 2021**, ~3.5× the ≥100 minimum. Listing-day open/close is exact from exchange archives. Sources: [investorgain](https://www.investorgain.com/report/number-of-ipos-per-year-in-india/546/), [chittorgarh year-wise](https://www.chittorgarh.com/report/list-of-ipo-by-year-fund-raised-success-mainboard/85/mainboard/).

### Deep Dive #1 decisions (settled)
- **Trust boundary:** label/backtest-critical fields — `listing_open`, `listing_close`, `qib_sub`, `nii_sub`, `retail_sub`, `price_band_high`, `segment` — are cross-checked against official NSE/BSE and never taken from an aggregator alone (config: `ingest.official_required_fields`). RHP-derived fields (`issue_pe`, `peer_median_pe`, `ofs_fraction`, anchor, lot/size, dates) may come from Chittorgarh as a validated single source.
- **History depth:** backfill **2021-01-01 → present** (config: `ingest.backfill_start_date`). Keeps NII sNII/bNII shape consistent, excludes pre-2020 COVID distortions, leaves headroom for folds.

### Deliverables built
- **Polite-scraper infra** [`data/sources/base.py`](src/ipo/data/sources/base.py): `RawCache` (immutable, SHA-256-keyed, never re-fetches/overwrites) + `PoliteClient` (rate-limit, exponential backoff, honest UA, `robots.txt` gate, `get_or_fetch` caching). `SourceError` degrades one source without crashing the run.
- **`CsvSeedSource`** [`data/sources/csv_seed.py`](src/ipo/data/sources/csv_seed.py): the deterministic, fully-tested ingestion path (curated real CSV; how the ≥100 sample is assembled). Schema-validate → fail loud.
- **`ChittorgarhSource`** [`data/sources/chittorgarh.py`](src/ipo/data/sources/chittorgarh.py): real polite `fetch` + a parser for the **stable schema.org microdata** (name, segment, issue price, listing close, gain%). Tested against a **real captured fixture** [`tests/fixtures/chittorgarh_recent_ipos.html`](tests/fixtures/chittorgarh_recent_ipos.html). Free-text page fields deliberately out of scope (too brittle to ship).
- **`ParquetRepository`** [`data/store/repository.py`](src/ipo/data/store/repository.py): idempotent record store + listing-label table (nested fields JSON-encoded; exact round-trip).
- **Label builder** [`data/labels/builder.py`](src/ipo/data/labels/builder.py): gross open/close returns vs band-top issue price; no label without listing data (withdrawn/deferred excluded, cost-free).
- **Hygiene** [`data/hygiene/clean.py`](src/ipo/data/hygiene/clean.py): cross-source merge with conflict detection on critical fields, segment tagging, bad-record log, validation routing.
- **Pipeline** [`data/ingest/pipeline.py`](src/ipo/data/ingest/pipeline.py) + CLI [`scripts/run_ingest.py`](scripts/run_ingest.py): sources → merge → hygiene → upsert → rebuild labels; idempotent + incremental.

### GATE 1 — met
- **Full pull builds both tables from scratch & updates incrementally:** [`tests/integration/test_ingest_pipeline.py`](tests/integration/test_ingest_pipeline.py) (also verified via `python scripts/run_ingest.py` → 7 records, 6 labels, 0 bad/conflicts).
- **A known past IPO's listing return matches the exchange figure:** Tata Technologies +140% (₹500→₹1200 open), LIC −8.62% (₹949→₹867.20 open), both verified against public figures.
- **SME tagged correctly:** the SME seed row is tagged `sme` and excluded from the mainboard set.
- **CI green:** ruff + black + mypy (strict) + **78 tests**.

### Decisions / notes
- Added deps: `pyarrow` (Parquet), `requests` (+`types-requests`), `beautifulsoup4` (HTML).
- NSE returns 403 to a bare client and Chittorgarh 403s the generic fetch tool — confirming the design split: `fetch` (network, operator-run with browser headers/session) is isolated from `parse` (pure, fixture-tested). The live HTML scrapers' bulk parsing beyond the microdata subset is left for the operator to calibrate against live responses (or superseded by the curated CSV / official APIs).

### Follow-ups
- Anchor-book parsing and broader official adapters (NSE/BSE subscription JSON) can be added incrementally behind `DataSource` without touching downstream layers.
- **≥100-IPO backfill — DECISION (operator, 2026-06-29): defer to pre-Phase-4.** Keep the 7-row plumbing seed; build Phases 2–3 on it (they don't need 100 rows); do the backfill as a dedicated task right before Phase 4, when feature needs are locked. Robots check done: Chittorgarh `User-agent: *` is `Allow: /` (only `/ipo/ipo_discussions.asp` blocked; AI-training bots blocked) → polite rate-limited detail-page scraping is permitted. Planned mechanism: extend `ChittorgarhSource` from microdata-only to per-IPO **detail-page** parsing (issue price, listing open/close, QIB/NII/retail, issue P/E, peer P/E, OFS), polite bulk pull of 2021–2025, then verify a sample against official NSE/BSE before it enters the backtest.

---

## Phase 2 — Feature layer + point-in-time correctness (done)

**Goal:** the leakage-free feature vector, computed identically in backtest and live.

### Deliverables built
- **`features/normalize.py`** — pure recipes: `clamp`, `winsorize`, `saturate` (`1-exp(-x/scale)`), `signed_saturate` (`tanh`). Scales live in config; applied by the scorer (Phase 3).
- **`features/gmp.py`** — `GmpQuote` + point-in-time `gmp_level_pct` / `gmp_slope_pct` (placeholder data until the Phase-5 scraper; quotes after `asof` ignored by construction).
- **`features/subscription.py`** — QIB/NII/retail multiples, gated on `book_closed` (open book → `None`).
- **`features/valuation.py`** — `issue_pe / peer_median_pe`; "no listed peers" → neutral-with-a-flag.
- **`features/anchor.py`** — 0..1 composite (marquee fraction × value-weighted lock-in × placement); recognized-anchor list in config, never in code; missing data → `None`.
- **`features/regime.py`** — −1..+1 trend/vol blend (pure; live index data injected later).
- **`features/build.py`** — `build_features(record, asof, *, gmp_series, market_regime, config)`: the Layer-2 output contract. Point-in-time by construction; missing features are explicit `None`s with `flags`.
- **`features/leakage.py`** — the firewall: `future_mutated_record` + `is_point_in_time_safe`, reusable by the Phase-4 backtest.
- Added `IPOFeatures.flags`; added the `features` config section (gmp/subscription/anchor/valuation/regime + `critical_features`).

### GATE 2 — met
- **Features build for a past IPO using only as-of data:** `test_features.py` + integration `test_features_pit.py` (ingested Tata Tech / LIC at subscription close).
- **Leakage suite fails on a leaky feature, passes otherwise:** `test_leakage.py` — `is_point_in_time_safe` is **True** for the real builder and **False** for one that peeks at the listing price; future GMP quotes ignored; label never changes features.
- **CI green:** ruff + black + mypy (strict) + **105 tests**.

### Decisions / notes
- **IPOFeatures stores raw point-in-time values**; normalization is applied in the scorer (Phase 3) so reasons can cite human-readable values ("QIB 203×"). Recipes live in `features/normalize.py`.
- **Critical features = `gmp_level`, `qib_sub`** (config) → missing/unclosed book ⇒ `INSUFFICIENT_SIGNAL` in Layer 3.
- For Phase 4: Deep Dive #4 prefers **Platt/sigmoid** as the default for ~100 IPOs (config currently `isotonic`); switch when wiring Phase 4.

### Follow-ups
- Phase 3 (scoring core): weighted score (normalize recipes + `feature_weights`), kill-flags, verdict thresholds + abstention, grounded reason. Calibrator stays the marked placeholder until Phase 4.

---

## Phase 3 — Scoring core (done)

**Goal:** features → verdict + grounded reason, with abstention and kill-flags. (No `ipo_advisor.py` skeleton existed in the repo; built fresh from Deep Dive #3.)

### Deliverables built
- **`model/scorer.py`** — `WeightedScorer` (implements `ScoringModel`): named, signed contributions over normalized feature values; weights are positive magnitudes, the scorer owns signs (GMP/subscription/anchor/regime add; valuation/OFS are brakes). `score = sum(contributions)`.
- **`model/killflags.py`** — `kill_flags(record, features, config)`: SME segment, collapsing GMP (slope ≤ threshold), near-total OFS, promoter litigation. Separate from the score on purpose.
- **`model/verdict.py`** — `evaluate(record, features, *, scorer, calibrator, config)`: **abstention first** (missing critical feature / unclosed book → `INSUFFICIENT_SIGNAL`), then kill-flag override → `SKIP`, then threshold the probability → APPLY/MARGINAL/SKIP.
- **`model/reason.py`** — grounded reason from the top contributions (cites values, e.g. "GMP +40%, QIB 200×"), watch-items from negatives, kill-flag notes, and the uncalibrated banner.
- **`model/calibrator_placeholder.py`** — `PlaceholderCalibrator` (logistic squash), `passes_reliability_gate = False`, version tagged `NOT FOR RELEASE`.
- Added `killflags` config section; `feature_weights` are now positive magnitudes.

### GATE 3 — met (verified live)
- `strong → APPLY` | prob withheld + banner | "Driven by GMP +40%, QIB 200×, anchor quality 1.00" | watch: OFS 20%.
- `fading-GMP → SKIP` | "Kill-flag override: collapsing_gmp" | watch: GMP slope −20%.
- `unclosed book → INSUFFICIENT_SIGNAL` | "missing qib_sub, book_closed".
- Calibrator is the marked placeholder; **no probability is shown** (probability `None`, banner present). CI green: ruff + black + mypy (strict) + **132 tests**.

### Decisions / notes
- **Probability is gated on `calibrator.passes_reliability_gate`** — until Phase 4, `Verdict.probability is None` and the reason carries the "UNCALIBRATED — not for decisions" banner; the verdict is still shown (Deep Dive #3, "overconfidence trap").
- `evaluate` takes the **record + features** (kill-flags need record-level context — segment, promoter litigation — that isn't in the feature vector).

### Follow-ups
- Phase 4 (calibration, the load-bearing gate) needs the ≥100-IPO backfill first. Then: walk-forward, Platt fit, reliability gate, look-ahead, report. (Done — see Phase 4 below.)

---

## Phase 4 — Backtest & Calibration, the load-bearing gate (done — GATE PASSED)

**Goal:** a trustworthy probability and earned thresholds, validated out-of-sample.

### Data backfill (the ≥100-IPO sample) — official, near-zero data caveat
Built an **official NSE source** ([`data/sources/nse.py`](src/ipo/data/sources/nse.py)) via the browser cookie-handshake (the same technique behind bhavcopy). All exact/official:
- master list + mainboard flag — `public-past-issues`; subscription **QIB/NII/retail** — `ipo-active-category` (works for past issues); listing **open/close** (label) — bhavcopy archive (old + UDiFF formats).
- [`scripts/run_backfill.py`](scripts/run_backfill.py): polite (rate-limited, cached, resumable), deduped → **311 mainboard IPOs (2021+)** written to [data/backfill/mainboard_ipos.csv](data/backfill/mainboard_ipos.csv) (committed, reproducible). 293 OOS-eligible (mainboard + closed book + QIB + label).
- **Kite not used** (no IPO-subscription endpoint; bhavcopy already free). **No paid subscription, no manual entry** — operator's questions answered.

### Calibration package + the gate
- [`calibration/label.py`](src/ipo/calibration/label.py) — net-of-cost label (exit at listing-day open; STT/DP/exchange/GST).
- [`calibration/reliability.py`](src/ipo/calibration/reliability.py) — reliability bins + ECE + Brier + AUC (rank-based).
- [`calibration/calibrate.py`](src/ipo/calibration/calibrate.py) — `PlattCalibrator` (Newton) + `IsotonicCalibrator` (PAV); versioned persist/load with feature-hash + label-def.
- [`calibration/backtest.py`](src/ipo/calibration/backtest.py) — walk-forward (no random folds), the 6-point gate, and the look-ahead shuffle.
- [`calibration/dataset.py`](src/ipo/calibration/dataset.py) + [`scripts/run_calibrate.py`](scripts/run_calibrate.py) → persisted [models/calibrator.json](models/calibrator.json) + [docs/CALIBRATION.md](docs/CALIBRATION.md).

### GATE 4 — PASSED (official-only model, GMP still Phase 5)
| Check | Result |
|---|---|
| discrimination | AUC **0.812** (floor 0.55) |
| calibration | ECE **0.073** (bound 0.10) |
| beats base rate | APPLY precision **83.7%** vs base **69.1%** |
| time-stable | early ECE 0.110 / late 0.087 |
| **look-ahead collapses** | shuffled AUC **0.472** (~0.5 → no leakage) |
| abstention excluded | yes |

Both gates CI-enforced: `test_calibration_gate.py` (reproduces the pass on committed data) and `test_layer3_calibrated.py` (Layer 3 loads the persisted calibrator → shows a probability, no banner). ruff + black + mypy + **154 tests** green.

### Decisions / notes
- Calibrator default switched to **Platt** (Deep Dive #4 for ~100 IPOs).
- **`critical_features` now `[qib_sub]`** for the official-only model (was `[gmp_level, qib_sub]`); Phase 5 re-adds `gmp_level` when GMP is integrated + recalibrated. The calibrator is valid for the subscription-driven feature configuration it was fit on.
- `IPORecord.lot_size`/`issue_size_cr` made optional (NSE doesn't provide them; not features).
- The strong official result (AUC 0.81) reflects 2021–2025 being a hot IPO market (base rate 69%); the look-ahead shuffle (0.47) confirms it's real signal, not leakage. Small-sample caveat stated in the report.

### Follow-ups
- Phase 5 (GMP): reconstruct historical GMP, wire into features, re-add `gmp_level` to critical, **re-run this exact calibration**, keep GMP only if it improves calibration. (Framework done — see Phase 5 below.)

---

## Phase 5 — GMP integration (framework done; gate RUN on hot-market data → GMP not earned)

**Goal:** add GMP, but only if it *earns* its weight (Deep Dive #5, the second sacred gate).

### Data-source decision (operator, 2026-06-29) — build framework now, defer the noisy historical pull
Investigated GMP feasibility and pricing:
- **No clean historical source.** Trackers JS-render GMP (investorgain), Chittorgarh paywalls it, ipowatch is live-only.
- **ipoalerts.in** API: `gmp` object is `sources:[{name,gmpPrice}]` + median — *exactly* our reconciler — but **current GMP only (no history)**, GMP is a paid add-on. **Ideal for LIVE going forward, not the backtest.**
- **IPOMatrix Pro ₹25k+GST/yr**: the only confirmed historical GMP (2021–2026), but a web platform (scrape logged-in), ~all-redundant with our free NSE data, and GMP may fail its own gate → **poor value; don't buy.**
- **Decision:** build the GMP framework (shaped to ingest ipoalerts' format for live), keep the historical re-calibration gate deferred; run it only if historical GMP is ever sourced.

### Deliverables built
- **`data/sources/gmp.py`** — `GMPPoint`, `GMPHistory` protocol, `reconcile` (median across sources + divergence/low-confidence flag), winsorization, `detect_spike_collapse` (manipulation → kill-flag), `has_sufficient_coverage` (coverage floor → abstain), `from_aggregator_rows` (ingests ipoalerts' shape), `CsvGmpHistory` (the operator/deferred-historical path), `to_quotes` (bridge to `features.gmp`).
- **`calibration/gmp_gate.py`** — `gmp_recalibration_gate`: runs the **same** walk-forward with vs without GMP and keeps GMP only if it worsens **neither** calibration (ECE) **nor** discrimination (AUC). The AUC guard is essential — a pure-noise feature can look "calibrated" by predicting the base rate.
- Added `gmp` config section; `GmpConfig`.

### GATE 5 — framework validated; real gate deferred
- The gate **mechanism is proven** on controlled data: `test_gmp_framework.py` shows an *informative* GMP is **kept** and a *pure-noise* GMP is **rejected** (discrimination collapses). Reconciliation/median, divergence-flagging, spike-collapse, and coverage-floor all tested.
- **`gate-5` is NOT tagged:** the real GMP re-calibration needs *historical* GMP for the 311 IPOs, which is deferred. It runs (and `gmp_level` returns to `critical_features`) once that data is sourced — feed it as a `gmp.csv` via `CsvGmpHistory`, or wire ipoalerts for live.
- ruff + black + mypy + **168 tests** green.

### GMP re-calibration gate — RUN on real point-in-time GMP (2026-06-30)

**Phase-5 GMP gate run on real point-in-time IPOMatrix data (2025–26, hot market, single source,
N≈99 / 39 OOS) → no significant marginal lift over the official QIB-led model → GMP stays out of
the shipped model, provisionally; revisit with cold-market point-in-time GMP from the recorder.**

- **Data:** point-in-time, day-by-day GMP for **99 of 101** mainboard 2025–26 IPOs (~1,817
  reconciled day-points), pulled from IPOMatrix/Chittorgarh's private JSON API. **Trial-only
  research pull — NOT a sanctioned ongoing source;** the AWS recorder remains the durable,
  multi-source, forward collection path. Raw GMP gitignored; only the derived report committed.
- **Method:** same IPOs scored **with vs without** GMP (level + as-of-close slope; the
  Allotted/Listed rows excluded by construction → not leaky), walk-forward, **3 splits** +
  paired-bootstrap CI on the AUC lift ([`scripts/run_gmp_gate.py`](../scripts/run_gmp_gate.py),
  `gmp_recalibration_gate`).
- **Result:** AUC lift **+0.008…+0.022 — every 95% CI straddles 0**; keep/cut **flips** across
  splits; APPLY precision ~unchanged (67%→71%). The leaky nikhilraj screen's inflated **+0.133
  collapsed to ~0** on clean data — the apparent GMP edge was mostly leakage; as-of-close GMP is
  largely redundant with QIB in a hot market. Full report: [GMP_GATE.md](GMP_GATE.md).
- **Decision:** **do NOT promote GMP into the score;** `critical_features` stays `[qib_sub]`.
  Boundaries: hot-market only (base 62%), single-source, small N; the spike-collapse kill-flag is
  untested here. Re-run the same gate when the recorder banks cold-regime point-in-time GMP.
- **174 tests green** (ruff + black + mypy strict).

### Follow-ups
- **Real GMP gate — DONE (2026-06-30, hot-market data only):** ran on 99 point-in-time 2025-26
  IPOs → **GMP not earned** (see subsection above). `gmp_level` stays OUT of `critical_features`;
  the calibrator is unchanged. **Re-run** `scripts/run_gmp_gate.py` when the recorder banks
  cold-regime point-in-time GMP — that, not more hot-market data, is the open question.
- **Live GMP (Phase 6 service):** wire ipoalerts' `gmp` object through `from_aggregator_rows` → `reconcile` → `to_quotes` at the subscription close.
- Phases 6 (service/API/notifier) and 7 (Windows `.exe` + Android APK) remain.

---

## Regime stress-test & cold-market flag (analysis, post-Phase-4)

Stress-tested the calibrated model by market regime (Nifty 3-month trend/drawdown at listing). Honest findings (full detail in [REGIME_STRESS.md](REGIME_STRESS.md), [REGIME_FIX.md](REGIME_FIX.md), [REGIME_SKWORLD.md](REGIME_SKWORLD.md)):
- **Ranking/selection edge survives ordinary cold** (cold APPLY ~83% vs cold base ~60%); on the larger independent 214-IPO cold sample, **cold ECE 0.083 (within tolerance)** — the earlier cold-ECE alarm was partly thin-sample.
- **Wiring `market_regime` in did not improve cold calibration OOS** (single 0.139, per-regime 0.115, both > 0.10; cold folds too thin). Landed outcome: **flag, don't force** — verdict appends "cold market — ranking reliable, probability less certain" at `market_regime ≤ −0.3`.
- **Deep-cold (2011–13 IPO winter, n=54, AUC ≈0.50)** logged as a known **unvalidated** limitation; system deliberately does **not** auto-abstain (would be a threshold fit to n≈1).
- The cold flag is **pure annotation** (read-only w.r.t. the decision); the `−0.3` threshold is an **untuned prior**. Kaggle (skworld) used **only** as independent replication — never in the calibrator.

---

## Phase 6 — Advisory service (done — GATE 6 PASSED)

**Goal:** fresh verdicts + windowed scoring + advisory push alerts, composed from the proven
layers. Built in six reviewed steps (each landed green on its own branch, merged on approval):

1. **`market_regime` wired FLAG-ONLY** ([`regime.py`](../src/ipo/calibration/regime.py), [`dataset.py`](../src/ipo/calibration/dataset.py), config `market_regime: 0.0`) — the cold flag activates in the live build, but its scorer weight is **0**, so the probability never moves (byte-equality proven). Append-only `update_nifty_csv` preserves the as-of clock. **Prereq #1 RESOLVED** (flag is LIVE), **prereq #2 RESOLVED** (`−0.3` re-checked read-only → flags 20% of all / 58% of known-cold; **unchanged**, [REGIME_RECHECK.md](REGIME_RECHECK.md)).
2. **`VerdictEngine`** ([`engine.py`](../src/ipo/service/engine.py)) — repo + calibrator + scorer + regime → verdicts, scored as-of the close (decision clock).
3. **Read-only REST API** ([`api.py`](../src/ipo/service/api.py)) — `GET /health|/ipos|/ipo/{id}|/verdict/{id}`; a thin reader, never re-derives the probability.
4. **`ScoringScheduler`** ([`scheduler.py`](../src/ipo/service/scheduler.py)) — windowed cadence (30 min in the subscription window, else 360), idempotent cycles, transition-tracked `became_apply`.
5. **`service/notify/`** — `Notifier` impls (Null/Log/Push; Telegram/email deferred behind config, **fail loud**) + `notify_crossings` firing once per APPLY crossing.
6. **`service/runner.py`** — `build_service` composition root + `main()` (scheduler loop + uvicorn).

### GATE 6 — PASSED (all five invariants survive composition)
End-to-end on the composed service ([`test_service_gate6.py`](../tests/integration/test_service_gate6.py)):

| # | Invariant | Evidence |
|---|---|---|
| 1 | Happy path | ingest(refresh)→score **311**→serve API→fire **185** APPLY crossings (185 pushed), windowed cadence |
| 2 | Calibration-sacred | cold flag fires on **58** IPOs, yet **MAX \|prob_service − prob_official\| = 0.0** |
| 3 | Reliability gate | gated → blessed number over API (0.3113); un-gated → `None` over API **and** number-free in all 293 notifications |
| 4 | Idempotent | 2nd cycle → identical verdicts, **0** dup alerts, **0** dup pushes |
| 5 | Advisory-only | API methods `GET` only; no mutating verbs / action paths |

Tag `gate-6-service`. **197 tests green; ruff/black/mypy (full tree) clean.** Scope held: **live GMP `None`** (out of the score until it earns its place, [GMP_GATE.md](GMP_GATE.md)); apps deferred to Phase 7.

### Decisions / notes
- **A feature stays out of the number until calibration earns it** — `market_regime` weight 0 (flag-only), `gmp_level` `None` live; symmetric, principled. The Phase-4 calibrator is byte-for-byte unchanged.
- Engine gained additive read-only `get_record` / `records` accessors (for the API / scheduler); existing behavior unchanged.
- Process: full `mypy` (incl. `tests/`) is the gate — an earlier `mypy src scripts` habit missed a test-only typing error (fixed, `f792236`); now always run the full tree.

### Follow-ups
- **Live GMP** (ipoalerts) stays out of the score until a **cold-market re-run of the Phase-5 gate** earns it; the recorder keeps banking.
- **Phase 7:** Windows `.exe` native shell (APK deferred).

---

## Housekeeping backlog (address in a dedicated pass AFTER Phase 6 — not mid-step)

- **Benign third-party test warning (Phase 6 step 3, the REST API):** `starlette.testclient`
  emits `StarletteDeprecationWarning: Using \`httpx\` with \`starlette.testclient\` is
  deprecated; install \`httpx2\``. It originates from FastAPI's TestClient import only — our
  code is unaffected and all tests pass. Resolve by pinning/migrating (httpx2, or a starlette
  pin) in a housekeeping pass; deliberately **not** addressed mid-step.
