# MASTER BLUEPRINT — Indian IPO Listing-Gains Advisor

### Claude Build Handoff Document

*A single, self-contained specification for building a modular, grounded, **calibrated IPO listing-gains advisory system** for Indian **mainboard** IPOs. It ingests official + grey-market data, computes point-in-time features, runs a calibrated model that outputs a decisive **verdict** (APPLY / MARGINAL / SKIP / INSUFFICIENT_SIGNAL), a **calibrated probability** of a positive listing, and a **grounded reason** — then surfaces all of it through a cross-platform app (**Windows `.exe` + Android APK**). The system is **purely advisory**: both legs are manual — the operator places the IPO bid and sells on listing day by hand, and the system never places an order. Written to be handed to Claude (running long sessions on a Claude Max plan) and built phase by phase. Grounded June 2026.*

---

## HOW TO USE THIS DOCUMENT WITH CLAUDE

Work it **top to bottom, one phase at a time.** Within a phase, build all of its parts to their acceptance criteria, write the tests, then make **one commit for the whole phase** when the major deliverable is done and its GATE passes.

**At the start of a phase, tell Claude:**
> "Follow the Engineering Ground Rules (Part I). We're building **Phase N**. Read its reference, build every deliverable to the GATE criteria, write the tests, update the Progress Log, then make one commit `feat(pN): …` and tag the gate."

**Rules of engagement:**
- **One commit per phase**, made only when the phase's major deliverable is built and its GATE passes. Tag the gate (`gate-N-name`). The committed tree must always be green (lint + types + tests).
- **Respect dependencies and gates.** Do not start a phase until the previous gate passes.
- Claude **must not**: hold app-signing keys, or place any real order of any kind. The system is advisory; the human operator does all bidding and selling by hand in Kite.
- When a decision is ambiguous, choose the **simpler, more robust, more testable** option.

---

# PART I — ENGINEERING GROUND RULES

Non-negotiable standards for every line of code. Re-read before each phase.

## 1. Modularity
- **One module = one job.** Ingestion, features, scoring/calibration, backtest, advisory service, apps, and (optional) sell-execution each live in their own package with a clear boundary.
- **Program to interfaces.** Define `Protocol`s for anything with more than one implementation — each data source (`DataSource`), storage (`Repository`), the scorer (`ScoringModel`), the calibrator (`Calibrator`), and the notifier (`Notifier`). **Nothing outside `data/sources/` imports a scraper client.**
- **Dependency injection**, no global mutable state, **pure functions for anything that touches point-in-time data** (this is what makes leakage-freedom enforceable).
- **Define each module's input/output contract up front** so downstream work proceeds against the interface.

## 2. Avoid Hard-Coding
- **All parameters live in versioned config** (`config/`): feature weights, verdict thresholds, kill-flag rules, source URLs, scrape cadence, calibration settings, notification channels. Layered: `default.yaml` ← env override ← env vars.
- **Secrets never in code or config.** Push-notification keys (and `KITE_*` only if Kite is used as a market-data source) come only from env/secrets interface; never committed, never logged.
- **Named constants** (NSE session times, listing-day sell-cost rates, GMP-update cadence) defined once in `core/`.

## 3. Standard Structure
```
ipo-advisor/
├── README.md
├── pyproject.toml                # deps + ruff/black/mypy/pytest config
├── .pre-commit-config.yaml
├── .gitignore                    # .env, data_store/, *.parquet, secrets/, dist/
├── .github/workflows/ci.yml      # lint + type-check + tests on every push
├── config/
│   ├── default.yaml              # weights, thresholds, kill-flags, cadence
│   ├── sources.yaml              # source URLs + scrape settings
│   └── env/                      # dev.yaml, prod.yaml
├── src/ipo/
│   ├── core/                     # types, Protocols, config loader, secrets, logging, NSE calendar, constants
│   ├── data/                     # LAYER 1 — Ingestion
│   │   ├── sources/              #   one adapter per source (NSE/BSE, SEBI/RHP, Chittorgarh, GMP trackers); ONLY place a source client is imported
│   │   ├── store/                #   Repository + ParquetRepository
│   │   ├── labels/               #   listing-day return builder (the supervised label)
│   │   └── hygiene/              #   dedupe, mainboard/SME tagging, bad-record logging
│   ├── features/                 # LAYER 2 — Feature engineering (point-in-time pure)
│   ├── model/                    # LAYER 3 — Scoring CORE
│   │   ├── scorer.py             #   transparent weighted score + feature contributions
│   │   ├── killflags.py          #   hard overrides → forced SKIP
│   │   ├── verdict.py            #   thresholds → APPLY/MARGINAL/SKIP + abstention
│   │   └── reason.py             #   grounded reason generator from top contributions
│   ├── calibration/              # LAYER 4 — Backtest & Calibration (calibration is SACRED)
│   │   ├── backtest.py           #   walk-forward over past IPOs, as-of snapshots
│   │   ├── calibrate.py          #   isotonic / Platt fit + persisted calibrator
│   │   └── reliability.py        #   reliability diagram + Brier/ECE checks
│   ├── service/                  # LAYER 5 — Advisory service (FastAPI)
│   │   ├── api.py                #   REST: /ipos, /ipo/{id}, /verdict/{id}
│   │   ├── scheduler.py          #   periodic ingest+score during subscription windows
│   │   └── notify/               #   Notifier protocol + push/Telegram/email
│   └── apps/                     # LAYER 6 — Cross-platform front end
│       ├── pwa/                  #   the dashboard (one UI, two packagings)
│       ├── desktop/              #   PyInstaller spec → Windows .exe (bundles service + webview)
│       └── android/              #   TWA/Capacitor wrapper → APK
├── scripts/                      # run_ingest.py, run_backtest.py, run_calibrate.py, run_service.py
├── tests/{unit,integration}/
└── data_store/                   # local parquet cache (gitignored)
```
Test files mirror the source tree. Production logic lives in `src/ipo/`, imported by notebooks, never copy-pasted.

## 4. No Temporary Patch Fixes
Solve the root cause, not the symptom. No band-aids, no commented-out code, no "TODO: fix later" in committed work. Source-site quirks (HTML changes, missing fields) are handled explicitly, with a test documenting the behavior — never papered over.

## 5. Code Comments
Comment the *why*. Docstrings on every public module/class/function (purpose, params, returns, invariants — e.g. "feature functions are point-in-time: inputs only data known at or before `asof`"). Reference the technique where relevant ("isotonic calibration; reliability diagram in `calibration/reliability.py`"). Keep comments truthful.

## 6. Git Best Practices (phase-commit model)
- **One commit per phase**, conventional-commit style (`feat(p4): backtest + calibration`). The tree is green at every commit.
- **Tag every gate** (`gate-1-ingest`, `gate-4-calibration`, …).
- **Never commit** secrets, signing keys, scraped raw HTML dumps, or anything in `.gitignore`.
- Run lint + type-check + tests before committing (pre-commit + CI enforce it).

## 7. Professional Standards
Clean readable code; **full static typing** (mypy/pyright green in CI); determinism (seed RNGs, version the calibrator and feature code); fail loudly and early (validate at boundaries, raise specific exceptions). Documentation is a first-class deliverable.

## 8. Proper Logging
Structured logging (JSON/key-value) configured once in `core/`. Levels: DEBUG/INFO/WARNING/ERROR/CRITICAL. Log every ingest run (per source, per IPO, record counts), every score with its feature vector and resulting verdict, every abstention with its reason, every calibration fit with its reliability metrics, and — for the optional sell leg — every order placement/fill/reject. **Never log secrets.** Timestamps in IST.

## Project-Specific Inviolable Rules
1. **Calibration is sacred.** No probability is shown to a user until the calibrator has passed a reliability check on out-of-sample IPOs (the "70% bucket" lists positive ~70% of the time). An uncalibrated number is a lie dressed as confidence. The placeholder logistic squash is for plumbing only and must be replaced before any user-facing release.
2. **Point-in-time correctness, always.** Every feature uses only data available **at or before the decision time** (subscription close), never values known only after listing. The backtest reconstructs as-of snapshots; the listing-day return (the label) never leaks into a feature. Final-day GMP is not available when you decide earlier — respect the as-of clock.
3. **The engine abstains when blind.** Missing a critical signal (GMP or QIB subscription) or an unclosed book → `INSUFFICIENT_SIGNAL`, never a fabricated number.
4. **Kill-flags override the score.** SME with thin financials, collapsing GMP in the final days, near-total OFS, and material promoter litigation force `SKIP` regardless of probability.
5. **GMP is unofficial and noisy.** Treat it as a sentiment proxy — good for *direction* (~70–75% historically), poor for *magnitude* — never as truth. The model leans on official subscription / anchor / valuation data for confidence; GMP sets the sign, not the certainty.
6. **Advisory only — both legs are manual.** The system never places any order. The operator places the IPO bid by hand (no bidding API exists anyway) and sells on listing day by hand. The system informs the decision; it never executes it.
7. **Honesty about outcomes.** A calibrated 70% still loses ~30% of the time. No profit is guaranteed on any single IPO. Listing-gain base rates swing hard with the market cycle. This is an engineering/research tool, not financial advice.
8. **Build in dependency order; respect the gates.**

---

# PART II — SYSTEM OVERVIEW & LOCKED DECISIONS

## What we are building
A service that, for each live/upcoming **mainboard** IPO, ingests official and grey-market data, computes point-in-time features, and emits three things and only these three:
1. **Verdict** — `APPLY` / `MARGINAL` / `SKIP` / `INSUFFICIENT_SIGNAL`
2. **Probability** — calibrated P(stock lists at a profit), 0–100%
3. **Reason** — plain language, every claim traced to a feature value, plus watch-items and kill-flags

…surfaced through a Windows `.exe` and an Android APK, with push alerts when a verdict crosses a threshold. The operator places the bid manually; the system optionally fires the listing-day sell.

## Realistic-expectations frame (keep visible)
- A listing pop is a **1–2 day demand/sentiment event**, not a fundamental repricing — which is why the model uses *relative* valuation, never DCF.
- GMP direction matches listing direction **~70–75%** of the time (2020–2025); magnitude is often well off. The signal is directional, not precise.
- The disciplines that decide the outcome are the boring ones: calibration, point-in-time honesty, abstaining when blind, and excluding manipulated SME issues.

## The pipeline
```
 SOURCES → INGEST (official + GMP) → FEATURES (point-in-time)
        → SCORE (weighted → calibrated) → VERDICT + REASON (+ kill-flags / abstention)
        → SERVICE (schedule, API, push) → APPS (.exe + APK)
```

## Locked decisions
| Decision | Choice | Why |
|---|---|---|
| Scope | **Mainboard IPOs only** | SME carries manipulation + SEBI-scrutiny risk; excluded or hard-penalized. |
| Strategy | **Listing-day flip (T+0/T+1)**, not hold | The forecast target is the listing pop, so only *relative* valuation matters, not intrinsic value. |
| Valuation | **Relative (issue P/E vs peer median)** only | DCF on a fresh IPO with short history is fragile and answers the wrong (multi-year) question. |
| Buy leg | **Manual** (operator bids in Kite) | Kite Connect has **no IPO-bidding API**; bids go through the Kite app/web with a UPI mandate. |
| Sell leg | **Manual** (operator sells on listing day) | Advisory by choice — the system signals the call; the operator executes. No order automation in scope. |
| Model | **Transparent weighted baseline → calibrated classifier** | Interpretable; every reason is a feature value; confidence is *earned* via calibration. |
| Storage | **Parquet** (+ optional DuckDB) | Matches the operator's existing stack; data volume is tiny. |
| App stack | **FastAPI service + PWA → Windows `.exe` (PyInstaller) + Android APK (TWA/Capacitor)** | Reuses the operator's proven hardware-monitor pattern; one UI, two packagings. |

## The data constraint map (what you can and cannot get — verified June 2026)
| Data | Free / available? | Source | Notes |
|---|---|---|---|
| Listing-day open/close (**the LABEL**) | **Yes, exact** | NSE/BSE archives | Issue price vs listing open/close → the supervised target. |
| Final subscription (QIB / NII / retail) | **Yes** | NSE/BSE, Chittorgarh | NII now splits sNII/bNII. QIB is the institutional-confidence signal. |
| Day-by-day subscription progression | **Partial** | NSE intraday, trackers | Final figures are easy; historical intraday progression is patchier. |
| Issue structure (OFS fraction, fresh vs OFS) | **Yes** | RHP (SEBI / Chittorgarh) | Heavy promoter exit (OFS) is a mild negative. |
| Anchor allotment + lock-in | **Yes** | exchange anchor disclosure / Chittorgarh | Engineer a 0–1 "anchor quality" score yourself. |
| Issue P/E + peer comparison | **Yes** | RHP peer-comparison table (SEBI-mandated) | Feeds relative valuation. |
| Market regime (Nifty trend / vol) | **Yes** | NSE / Yahoo Finance | Composite for listing-window conditions. |
| **Current** GMP | **Yes (live)** | GMP trackers (Chittorgarh, IPOWatch, IPO360, investorgain) | Unofficial; updated ~every 30 min during active hours. |
| **Historical** GMP series | **Hard** | scrape per-IPO from trackers | No official archive; non-standard, noisy, sources disagree. Build a scraper (Phase 5). |
| **IPO bid placement via API** | **No** | — | Manual in Kite app/web only. The system alerts; the human bids. |
| **Listing-day sell** | **Manual by choice** | Kite app/web | A sell *could* be API-automated, but this system keeps it manual and advisory. |

## Reference constants (researched — hardcode but keep rates in config)
**Kite Connect (verified June 2026)**
- No IPO-bidding endpoint, and this system places **no** orders — so Kite is not required for the core advisory. (Market-regime data can come from NSE/Yahoo.) Noted only because the operator already uses Kite for their equity system.

**Listing-day SELL cost (NSE delivery / CNC, verified June 2026)** — needed to report *net* listing gain
- Brokerage: **₹0** (delivery). STT: **0.1% on the sell** (dominant). DP charge: **₹15.34 per ISIN per sell-day, flat.** Exchange ~0.00297%, GST 18% on (brokerage+exchange), SEBI ₹10/cr, stamp nil on sell. The advisory report should show gross *and* net-of-cost listing gain so the verdict reflects what the operator actually keeps.

**GMP reality**
- Directional accuracy ~70–75% (2020–2025); magnitude often off. Unregulated, manipulable, no central book. Watch for SEBI's floated **"when-listed" platform** — if it launches, it becomes an official, free substitute for grey-market GMP and the Phase 5 scraper can be retired.

---

# PART III — THE LAYERS

## Layer 1 — Ingestion
**Goal:** a clean, deduplicated, mainboard-tagged record per IPO, plus the listing-day label, reproducible on demand.
One adapter per source behind a `DataSource` protocol; **only `data/sources/` knows a source exists.** Official sources first (NSE/BSE subscription + listing prices, SEBI/Chittorgarh RHP fields, anchor disclosures); GMP deferred to Phase 5. Be a polite scraper: respect robots/ToS, rate-limit, cache raw responses immutably, prefer official endpoints over aggregators where both exist. **Output contract:** a versioned Parquet table of IPO records + a `listing_return` label table.

## Layer 2 — Features (point-in-time pure)
**Goal:** the feature vector the model scores, computed identically in backtest and live.
Feature families: **GMP** (level + final-days slope), **subscription** (QIB/NII/retail multiples), **anchor quality** (0–1), **relative valuation** (issue P/E ÷ peer median), **issue structure** (OFS fraction), **market regime** (−1..+1). Each is a pure function of data **known at the decision time**. The backtest reconstructs as-of snapshots; CI leakage tests assert that no feature reads post-listing data and that the label never appears in an input. **Output contract:** `build_features(ipo, asof) → IPOFeatures`, point-in-time by construction, leakage tests green.

## Layer 3 — Scoring core
**Goal:** features → one calibrated probability → decisive verdict → grounded reason.
A transparent weighted score (interpretable, every contribution named) feeds the calibrator (Layer 4). `killflags.py` can force `SKIP`; `verdict.py` applies the `APPLY`/`MARGINAL`/`SKIP` thresholds and the abstention path; `reason.py` templates the top positive contributions plus watch-items from the negatives. This layer is the working skeleton already drafted (`ipo_advisor.py`) — port it here, split into the four modules, and wire the real calibrator in place of the logistic placeholder. **Output contract:** `evaluate(features) → Verdict{verdict, probability, reason, watch, kill_flags}`.

## Layer 4 — Backtest & Calibration (SACRED)
**Goal:** make the probability trustworthy and the thresholds earned.
Label ≥100 past mainboard IPOs with their actual listing-day return; run **walk-forward** over them using as-of feature snapshots; **fit a calibrator** (isotonic regression or Platt scaling) on the held-out folds; verify with a **reliability diagram** plus Brier score / expected-calibration-error. Then tune the Layer-3 weights and the verdict cutoffs against backtested outcomes. **Output contract:** a persisted, versioned calibrator + a calibration report. Nothing user-facing ships until this gate passes.

## Layer 5 — Advisory service
**Goal:** keep verdicts fresh and push them out.
FastAPI app: a **scheduler** that ingests + scores on a cadence (denser — e.g. every ~30 min — during open subscription windows, since GMP moves then), a small **REST API** (`/ipos`, `/ipo/{id}`, `/verdict/{id}`), and a `Notifier` that pushes when a verdict crosses a threshold ("StrongCo → APPLY, 72%"). Stateless reads off the Parquet store + calibrator. **Output contract:** a running service the apps consume.

## Layer 6 — Cross-platform apps (the "does everything" deliverable)
**Goal:** one dashboard, shipped as a Windows `.exe` and an Android APK.
A single **PWA** dashboard (IPO list with verdict badge, probability, reason, watch/kill flags, gross & net listing-gain estimate, subscription/GMP timeline). Two packagings of the same UI:
- **Windows `.exe`** — PyInstaller bundles the FastAPI service + the PWA served locally + a webview shell; self-contained, runs the whole pipeline on the desktop.
- **Android APK** — wrap the PWA (TWA via Bubblewrap, or Capacitor) pointing at the operator's service endpoint; receives push notifications.
**Output contract:** installable `.exe` and signed `.apk`, both showing live verdicts.

---

# PART IV — THE BUILD PROGRAM (phases; one commit each)

> **Note:** the GMP recorder is a separate, always-on data-collection project (its own repo), not a phase here. It must be deployed early and run in parallel, because GMP can only be collected forward in time. Phase 5 depends on its output.

## PHASE 0 — Foundation & scaffolding
**Goal:** skeleton, config/secrets, logging, NSE calendar, core contracts.
**Deliverables:** repo with the Part-I structure; `pyproject.toml`, pre-commit, CI; `core/config.py` (layered loader) + `core/secrets.py`; `core/logging.py`; `core/calendar.py` (NSE trading-day/IST); `core/types.py` + `core/interfaces.py` (`DataSource`, `Repository`, `ScoringModel`, `Calibrator`, `Notifier` Protocols); the `IPORecord` + `IPOFeatures` data models.
**GATE 0:** config loads & merges by env; a fake of each Protocol type-checks; CI green. Tag `gate-0-foundation`.

## PHASE 1 — Official ingestion + labels
**Goal:** clean IPO records + listing-day labels from official/aggregator sources.
**Deliverables:** `data/sources/` adapters (NSE/BSE subscription + listing prices, SEBI/Chittorgarh RHP fields, anchor disclosures) behind `DataSource`; `data/store/ParquetRepository`; `data/labels/` (issue price vs listing open/close → `listing_return`); `data/hygiene/` (dedupe, mainboard/SME tagging, bad-record logging); polite-scraper utilities (rate-limit, raw-response cache, ToS-aware).
**GATE 1:** a full historical pull builds the IPO table + label table from scratch and updates incrementally; a known past IPO's listing return matches the exchange figure; SME issues are correctly tagged. Tag `gate-1-ingest`.

## PHASE 2 — Feature layer + point-in-time correctness
**Goal:** the feature vector, leakage-free, identical in backtest and live.
**Deliverables:** `features/` (GMP placeholder, subscription, anchor quality, relative valuation, OFS, market regime) as point-in-time pure functions; as-of snapshot reconstruction; CI leakage suite (no post-listing data in any feature; label never an input; as-of clock respected).
**GATE 2:** features build for a past IPO using only as-of data; the leakage suite **fails** on an intentionally leaky feature and passes otherwise. Tag `gate-2-features`.

## PHASE 3 — Scoring core
**Goal:** features → verdict + reason, with abstention and kill-flags.
**Deliverables:** port `ipo_advisor.py` into `model/scorer.py`, `killflags.py`, `verdict.py`, `reason.py`; unit tests for each verdict path (APPLY, MARGINAL, SKIP, INSUFFICIENT_SIGNAL, kill-flag override); reason strings cite real feature values.
**GATE 3:** the three demo cases (strong → APPLY, fading-GMP → SKIP via kill-flag, unclosed book → INSUFFICIENT_SIGNAL) produce correct, grounded output; calibrator is still the placeholder and is clearly marked not-for-release. Tag `gate-3-scoring`.

## PHASE 4 — Backtest & Calibration *(the load-bearing gate)*
**Goal:** a trustworthy probability and earned thresholds.
**Deliverables:** `calibration/backtest.py` (walk-forward over ≥100 labeled mainboard IPOs, as-of snapshots); `calibrate.py` (isotonic/Platt fit, persisted + versioned); `reliability.py` (reliability diagram + Brier + ECE); weight/threshold tuning against backtested outcomes; a written calibration report.
**GATE 4:** the reliability diagram shows the predicted-vs-actual buckets tracking the diagonal within tolerance (e.g. the 0.6–0.8 bucket lists positive within a stated band); the overfit-dummy and look-ahead checks behave; the calibrator is persisted and loaded by Layer 3. **No user-facing release before this passes.** Tag `gate-4-calibration`.

## PHASE 5 — GMP integration

> **⚠️ Phase 5 prerequisite — the GMP recorder (separate, parallel project).**
>
> This phase cannot execute until real, point-in-time, day-by-day GMP data exists, and that data can only be collected going forward — no usable historical archive exists (a level-only screen on a leaky public set gave an inflated +0.133 AUC upper bound over total subscription; inconclusive, see Phase 5 notes). GMP is gathered by a standalone always-on recorder deployed on AWS, maintained as its own repository outside this build program (it records only — never scores or ranks; append-only, timestamped, multi-source; see its own README).
>
> **Sequencing:** deploy the recorder early and run it in parallel with the rest of the build — every delayed month is un-rederivable GMP history. Phase 5 proper runs only once the recorder has banked ~75+ mainboard IPOs of point-in-time GMP, at which point GMP (level and slope) is tested against the re-calibration gate and must beat the official-only baseline (~84% APPLY precision / current calibration) to stay in. Until then the shipping model is official-only, which already passes its gates.

**Goal:** add the messiest, most-weighted feature — after the official-data model already works.
**Deliverables:** `data/sources/gmp_*` scraper(s) reconstructing historical GMP series (level + final-days slope) from trackers; wire GMP into `features/`; **re-run Phase 4 calibration** with GMP included and compare reliability/Brier with and without it; document GMP source disagreement and noise.
**GATE 5:** GMP series reconstruct for past IPOs; the recalibrated model is **at least as well-calibrated** as the official-only model; GMP enters as a sentiment/direction feature, not a magnitude oracle. Tag `gate-5-gmp`.

## PHASE 6 — Advisory service
**Goal:** fresh verdicts + push alerts.
**Deliverables:** `service/api.py` (REST), `service/scheduler.py` (windowed ingest+score cadence), `service/notify/` (`Notifier` + push/Telegram/email); the service reads the Parquet store + persisted calibrator; health/status endpoint.
**GATE 6:** the service runs on a schedule, serves current verdicts over the API, and fires a push when a verdict crosses a threshold. Tag `gate-6-service`.

## PHASE 7 — Cross-platform apps (Windows `.exe` + Android APK)
**Goal:** the "does everything" front end on both platforms.
**Deliverables:** `apps/pwa/` (the dashboard: IPO list, verdict badge, calibrated probability, grounded reason, watch/kill flags, gross & net listing-gain estimate, subscription/GMP timeline); `apps/desktop/` (PyInstaller spec bundling the FastAPI service + locally-served PWA + webview shell → **Windows `.exe`**); `apps/android/` (TWA via Bubblewrap or Capacitor wrapper → **signed APK** pointing at the operator's endpoint, with push). Signing keys are the operator's, never Claude's.
**GATE 7:** the `.exe` launches the whole pipeline and shows live verdicts offline-capable on Windows; the APK installs and shows the same verdicts with push working. Tag `gate-7-apps`.

## PHASE 8 — Operate & maintain *(ongoing)*
Re-run Phase 4 calibration each quarter and after market-regime shifts (listing-gain base rates drift). Monitor source-site changes (scrapers break silently). Watch for SEBI's "when-listed" platform — adopt it as the official GMP substitute if it launches. Honest periodic audit: did APPLY verdicts actually list positive at the calibrated rate? If not, recalibrate or narrow scope. The program is maintained, never "finished."

---

# PART V — PROGRESS LOG
*Claude updates this at the end of every phase. Keep it in the repo (`docs/PROGRESS.md`).*

| Date | Phase | Status | Commit / tag | Tests | Notes / decisions / follow-ups |
|---|---|---|---|---|---|
| | P0 | ☐ todo / ◐ in-progress / ☑ done | | | |
| | P1 | | | | |
| | … | | | | |

**Gate status:** 0 ☐ · 1 ☐ · 2 ☐ · 3 ☐ · 4 ☐ · 5 ☐ · 6 ☐ · 7 ☐

---

*This is an engineering and research reference, not financial advice. The author/operator is not a SEBI-registered investment adviser. Grey-market premium is unofficial, unregulated data and is not a guarantee of listing price or returns. A calibrated probability is an estimate, not an assurance — a well-calibrated 70% still fails ~30% of the time, and listing-gain base rates vary sharply with the market cycle. Nothing here is a recommendation to apply to, buy, or sell any security. The calibration gate, the point-in-time rule, the kill-flags, and the abstention path are mandatory.*
