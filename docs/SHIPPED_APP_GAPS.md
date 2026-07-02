# Shipped App — What's Wired, What Isn't, and What It Takes to Go Live

Audit date: 2026-07-03. Scope: the packaged Windows app (NSIS `.exe` and the MSIX/`.appx`) —
i.e. the Electron shell + the PyInstaller'd Python engine sidecar as they actually run on an
end user's machine, versus what exists in the repo but is not connected to that running app.

## Bottom line

The shipped app is a **complete, correct advisory *engine* + UI + packaging that runs on frozen
sample data.** The scoring engine is real and gated (Platt calibrator, GATE 4, AUC 0.812 / ECE
0.073 on 311 official NSE IPOs). But the **entire live-data half is designed and never wired in**:
the running app never ingests, so it shows the same static demo verdicts forever. It therefore does
**not** meet the Phase-7 gate line "shows **live** verdicts, fires native notifications on **APPLY
crossings**" ([07_Phase7_App.md](deep_dives/07_Phase7_App.md), §"BUILD loop" / "Sequence summary").

This was the phased plan, not an accident — Phases 1–6 built and gated the engine on real official
data; Phase 7 put a UI + genuine-software packaging on it; the *live feed into the running app* was
the seam left for "operate & maintain." The demo store was the stand-in.

---

## What IS wired and working

- **Sidecar lifecycle** — Electron spawns the engine on a free port, health-gates `/health`, tears
  it down on every exit path; tray, remembered window state, startup toggles, splash.
  ([apps/desktop/src/main.ts](../src/ipo/apps/desktop/src/main.ts), [sidecar.ts](../src/ipo/apps/desktop/src/sidecar.ts))
- **The scoring engine** — features → scorer → kill-flags → verdict → grounded reason → **calibrated
  probability**, reliability-gated. Uses the real committed Platt calibrator (`models/calibrator.json`).
  ([service/engine.py](../src/ipo/service/engine.py), [model/](../src/ipo/model))
- **Read-only API + React UI** — the UI reads engine output verbatim (all five invariants hold);
  cost overrides recompute net-of-cost History; verdict-transition log + alert center render.
- These all operate correctly — **on the static store**.

---

## What is NOT wired / dead in the shipped app

1. **No live data ingestion (the core gap).** `runner.main()` calls `build_service(...)` with **no
   `refresh`** and **no `push_transport`** ([service/runner.py](../src/ipo/service/runner.py) `main()`).
   The scheduler loop runs every cadence but its ingest branch (`if self._refresh is not None`,
   [scheduler.py](../src/ipo/service/scheduler.py)) never executes. The record store is the **static
   bundled demo** (7 historical + 3 fabricated), provisioned once from the frozen `_seed`. Verdicts
   never change.

2. **The `refresh` ingestion hook was never implemented.** It is a designed-in seam that is `None`
   everywhere. Even the GATE-6 test's "ingest" was a stub that only *counted* calls over a pre-loaded
   CSV — no code anywhere assembles live data → `IPORecord`s → store at runtime.

3. **The NSE official adapter is unused by the app.** [data/sources/nse.py](../src/ipo/data/sources/nse.py)
   can fetch the IPO master list + **QIB/NII/retail subscription** (`ipo-active-category`) + listing
   labels (bhavcopy), and it's tested — but it's only called by the offline
   [scripts/run_backfill.py](../scripts/run_backfill.py) to build the committed historical CSV. It
   never touches the running app.

4. **The whole ingest layer is offline-only.** [data/ingest/pipeline.py](../src/ipo/data/ingest),
   `data/hygiene`, `data/labels`, and every `data/sources/*` adapter (nse, chittorgarh, csv_seed,
   gmp) run only via CLIs (`run_ingest.py`, `run_backfill.py`), never inside the sidecar. The app
   uses only `ParquetRepository` (read).

5. **The Python notifier is dead.** Default config is `channel: none` → `NullNotifier`
   ([config/default.yaml](../config/default.yaml)). On static data there are no APPLY crossings
   anyway, so `notify_crossings` never fires. **The "native notifications on APPLY crossings" the
   Phase-7 gate requires never happen.** The renderer-side toasts
   ([apps/pwa/src/notifications.ts](../src/ipo/apps/pwa/src/notifications.ts)) also key off the
   static transition log, which never gains a new crossing.
   *Landmine:* `config/env/prod.yaml` sets `channel: push` with no transport → that path raises
   `ValueError` and would crash the engine; the app avoids it only by running the `dev`/default env.

6. **Fabricated demo data ships.** "Greenspark Energy", "NovaCore Semiconductors", "Helios Wind",
   and "Deferred Demo Issue" are invented fixtures ([scripts/seed_demo_store.py](../scripts/seed_demo_store.py));
   the real names (Zomato, Nykaa, …) carry curated/synthesized subscription splits + sparklines. A
   Store user sees exactly this frozen set — including companies that don't exist.

7. **`market_regime` runs on frozen data.** Wired flag-only (scorer weight 0) but computed against a
   **static bundled `nifty.csv`** — the cold-market flag evaluates against stale index history. It
   never moves the number (by design), but it isn't "live" either.

8. **"Recalibrated N×" is a display counter, not real re-fitting.**
   ([apps/pwa/src/recalib.ts](../src/ipo/apps/pwa/src/recalib.ts)) The calibrator is static (fit once,
   committed); no runtime re-calibration happens.

9. **Auto-update not wired** (no `electron-updater` in the shell). The Phase-7 doc explicitly allows
   deferring this, and the Microsoft Store delivers updates anyway — a known deferral, not a defect.

10. **GMP is out** — it failed its own gate ([GMP_GATE.md](GMP_GATE.md)); `features/gmp.py` is unused
    at runtime. This one is *by design*, not a gap.

---

## What it takes to make it genuinely live

1. **Implement a real ingestion `refresh`.** Use the existing NSE adapter: pull the master /
   upcoming list → find open/closing IPOs → fetch each one's subscription (`NseClient.subscription`)
   → build `IPORecord`s → `repo.upsert_many`. **`qib_sub` is the *only* critical feature and NSE
   provides it**, so this alone yields real verdicts (anchor/valuation/OFS are non-critical
   enhancements). This is a new orchestrator (the offline pipeline builds a CSV, not runtime records).

2. **Wire that `refresh` into `runner.main()`** — pass it to `build_service(refresh=...)`. It then
   fires on the scheduler's existing cadence (30 min while a book is open, else 360). Make ingestion
   failures degrade gracefully (a `SourceError` must not crash the sidecar).

3. **Turn on real notifications.** With live crossings occurring, either give the Python notifier a
   real transport, or rely on the renderer toasts (already wired; `AppUserModelId` is set) — they
   start firing on genuine APPLY crossings once the data moves.

4. **Enhancement features have no live source (the hard, deferred part).** `anchor_quality`,
   `relative_valuation` (`issue_pe` / `peer_median_pe`), and `ofs_fraction` come from the RHP /
   prospectus + anchor filings — no adapter parses these live (deliberately "too brittle to ship",
   [PROGRESS.md](PROGRESS.md) Phase 1). Without them the engine still scores (they're non-critical),
   just with less signal. Building them is a project in itself.

5. **Handle operational reality.** NSE's anti-bot **cookie handshake**, rate limits, retries, and
   caching now run from **end-user machines** — a different reliability/ToS problem than one operator
   backfilling. Consider: a hosted API you control that does the scraping once and the app polls
   (removes per-user scraping + ToS risk), versus scraping from each install.

6. **Remove the fabricated upcoming companies** — the live feed replaces them. Until then, anything
   published must be labelled honestly as sample/historical data.

7. **Fix the `prod` notify landmine** — either wire a push transport or change `prod.yaml`'s
   `channel` so the engine can't be started into a crashing config.

### Recommendation

Do **not** publish the current build to the public Store as a "live IPO advisor" — it isn't one yet.
Either (a) build items 1–3 to make it genuinely live, or (b) ship it as an explicitly-labelled demo
with the fabricated companies removed. Items 4–5 are the real engineering beyond a minimal live feed.
