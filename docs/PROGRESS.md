# Progress Log — IPO Listing-Gains Advisor

Updated at the end of every phase (MASTER_BLUEPRINT Part V). The committed tree is
green (lint + types + tests) at every phase commit.

| Date | Phase | Status | Commit / tag | Tests | Notes / decisions / follow-ups |
|---|---|---|---|---|---|
| 2026-06-29 | P0 | ☑ done | `feat(p0): foundation & scaffolding` / `gate-0-foundation` | 38 passing | Foundation built; GATE 0 met. See details below. |
| | P1 | ☐ todo | | | Official ingestion + labels. |
| | P2 | ☐ todo | | | Features + point-in-time leakage suite. |
| | P3 | ☐ todo | | | Scoring core (port `ipo_advisor.py`). |
| | P4 | ☐ todo | | | **Calibration — load-bearing gate.** Needs ≥100 labeled IPOs. |
| | P5 | ☐ todo | | | GMP integration + re-calibration gate. |
| | P6 | ☐ todo | | | Advisory service (API / scheduler / notifier). |
| | P7 | ☐ todo | | | Windows `.exe` + Android APK. |
| | P8 | — | | | Operate & maintain (ongoing). |

**Gate status:** 0 ☑ · 1 ☐ · 2 ☐ · 3 ☐ · 4 ☐ · 5 ☐ · 6 ☐ · 7 ☐

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
- **Phase 1 open item (flag for operator):** confirm we can assemble **≥100 past mainboard IPOs with clean listing-day labels** for the Phase-4 calibration sample. Raised now per the build instructions.
- History-depth and aggregator-trust open questions from Deep Dive #1 to settle during Phase 1.
