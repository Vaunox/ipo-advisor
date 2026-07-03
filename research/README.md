# research/ — dead code, excluded from the build

Code that is **not** part of the shipped product and must never be bundled into the app. It is kept
intact for a possible future re-test, not for production use.

## Why this is guaranteed out of the shipped artifact

The build packages only `src/ipo/` (the engine) and the PWA — never this directory:

- **PyInstaller engine** (`packaging/ipo-engine.spec`): the bundle's Python is
  `collect_submodules("ipo")` (i.e. `src/ipo/`) plus explicit third-party deps and a fixed `datas`
  list (config / models / nifty). `research/` is not under `src/ipo/`, not in `datas`, not the entry
  point (`packaging/engine_entry.py`), and not on `pathex` — so it **cannot** be collected.
- **Electron app** (`src/ipo/apps/desktop/package.json`): `extraResources` copies only the built PWA
  (`../pwa/dist`) and the frozen engine dist (`packaging/dist/ipo-engine`). Raw Python / `scripts/` /
  `research/` are never copied.
- **pip package** (`pyproject.toml`): `packages.find where = ["src"]` — `research/` is not installed.

Dev tooling (ruff / black / mypy / pytest) still covers `research/` so it stays valid for a re-run.

## Contents

Backfill + extraction + gate for the three **enhancement features that FAILED the re-calibration
gate** (2026-07-03, hot-market N=293) — OFS, relative valuation, anchor:

- `backfill_enhancement.py` — Chittorgarh research pull: OFS extraction, peer-P/E parsing (RHP
  peer-comparison table), NSE↔Chittorgarh name join, name-verification. Raw HTML is cached under
  `data_store/_enhancement/` (gitignored).
- `run_enhancement_gate.py` — the with-vs-without re-calibration gate (calibrator refit per arm,
  ECE + AUC + bootstrap CI), gated separately per feature with the valuation hand-QA.

## ⚠️ Before touching these in v2

**Failed re-calibration gate (2026-07-03, hot-market N=293); retained here for possible v2 re-test;
excluded from build; do NOT ship or wire live without re-running the gate.** The features' scorer
weights are `0.0` in `config/default.yaml` (inert, byte-equality proven), and two findings actively
contradict the blueprint — see `docs/ENHANCEMENT_GATE.md`:

- the **OFS kill-flag is backwards** on our data (do not implement `OFS→SKIP`);
- valuation's apparent lift was an **outlier artifact** that evaporated under peer-P/E hand-QA.
