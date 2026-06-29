# Progress Log — IPO Listing-Gains Advisor

Updated at the end of every phase (MASTER_BLUEPRINT Part V). The committed tree is
green (lint + types + tests) at every phase commit.

| Date | Phase | Status | Commit / tag | Tests | Notes / decisions / follow-ups |
|---|---|---|---|---|---|
| 2026-06-29 | P0 | ☑ done | `feat(p0): foundation & scaffolding` / `gate-0-foundation` | 38 passing | Foundation built; GATE 0 met. See details below. |
| 2026-06-29 | P1 | ☑ done | `feat(p1): official ingestion + labels` / `gate-1-ingest` | 78 passing | Ingestion + labels; GATE 1 met. Sample feasibility confirmed; two DD#1 decisions made. |
| | P2 | ☐ todo | | | Features + point-in-time leakage suite. |
| | P3 | ☐ todo | | | Scoring core (port `ipo_advisor.py`). |
| | P4 | ☐ todo | | | **Calibration — load-bearing gate.** Needs ≥100 labeled IPOs. |
| | P5 | ☐ todo | | | GMP integration + re-calibration gate. |
| | P6 | ☐ todo | | | Advisory service (API / scheduler / notifier). |
| | P7 | ☐ todo | | | Windows `.exe` + Android APK. |
| | P8 | — | | | Operate & maintain (ongoing). |

**Gate status:** 0 ☑ · 1 ☑ · 2 ☐ · 3 ☐ · 4 ☐ · 5 ☐ · 6 ☐ · 7 ☐

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
- Phase 2 (features) consumes `IPORecord` + the as-of clock; point-in-time leakage suite next. Anchor-book parsing and broader official adapters (NSE/BSE subscription JSON) can be added incrementally behind `DataSource` without touching downstream layers.
- **≥100-IPO backfill — DECISION (operator, 2026-06-29): defer to pre-Phase-4.** Keep the 7-row plumbing seed; build Phases 2–3 on it (they don't need 100 rows); do the backfill as a dedicated task right before Phase 4, when feature needs are locked. Robots check done: Chittorgarh `User-agent: *` is `Allow: /` (only `/ipo/ipo_discussions.asp` blocked; AI-training bots blocked) → polite rate-limited detail-page scraping is permitted. Planned mechanism: extend `ChittorgarhSource` from microdata-only to per-IPO **detail-page** parsing (issue price, listing open/close, QIB/NII/retail, issue P/E, peer P/E, OFS), polite bulk pull of 2021–2025, then verify a sample against official NSE/BSE before it enters the backtest.
