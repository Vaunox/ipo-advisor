# Operations Manual — how to keep the IPO Advisor running

*This is the **how** — the living procedures you actually run to operate and maintain the app when
you return to it occasionally. It is deliberately separate from [`docs/PROJECT_LOG.md`](../docs/PROJECT_LOG.md),
which is the **why** — the closed, archival evidence for how the model is shaped. When you come back
in six months to recalibrate or rebuild, read this file, not the codebase.*

**The scripts stay where they are** (`scripts/`) — they are wired and used. This folder documents
them; it does not relocate anything. Run everything **from the repo root** with the project venv:

```
# Windows (this machine)
.venv\Scripts\python.exe scripts\<name>.py [args]
# …or activate first:  .venv\Scripts\Activate.ps1   then:  python scripts\<name>.py
```

The golden rule that governs all of this: **a feature is never in the number until calibration earns
it, and the shipped calibrator never changes silently.** Recalibration produces a *candidate* you
review and promote by hand; nothing here auto-swaps the model users run.

---

## 1. Routine health checks — run periodically, read the result

None of these change the model. Run them after a batch of new listings, or on a calendar reminder.

| Check | Command | When | Reads OK as… | Concerning result |
|---|---|---|---|---|
| **Data-source heartbeat** | `python scripts/run_heartbeat.py` | Monthly, and before any recalibration | `OK` (all fresh) or `WARN` (expected stale feeds — see §4) | **`ERROR — a required artifact is MISSING`** (exit 1): `models/calibrator.json` / `reliability.json` / a `data/backfill/*.csv` is gone. Restore it. |
| **Verdict-accuracy / drift monitor** | `python scripts/run_accuracy_monitor.py` | Quarterly, or after ~20+ new listings | `OK - no drift` | **`DRIFT ALERT`** (exit 1): recent-window APPLY-precision Wilson-CI sits **entirely below** the OOS baseline, or recent ECE exceeds tolerance. → investigate, then recalibrate (§2). `INCONCLUSIVE` = recent window below `--min-window`, not judged. |
| **T+3 settlement stability** | `python scripts/run_t3_stability.py` | Yearly, or after a settlement-rule change | `STABLE` (ECE shift ≤ 0.030, CIs overlap) | `DIFFERENCE` — but read the cause. Expected to read `DIFFERENCE` on the full 358 set purely from cold-era composition in the pre-cutover bucket (see [PROJECT_LOG §4.6](../docs/PROJECT_LOG.md#46-t3-stability)); a *settlement-driven* difference (matched composition) is the real signal → recalibrate on post-cutover data. **Regenerates `docs/T3_STABILITY.md`.** |
| **Recalibration-reproduces (dry run)** | `python scripts/run_recalibration_check.py` | Before trusting any re-fit; part of the recalibration ritual | **`REPRODUCES` (max delta 0.0)** — the fit is deterministic | **`MISMATCH`** (exit 1): the shipped calibrator is stale vs current data/code. → run the recalibration ritual (§2). **Writes nothing** — safe to run anytime. |

**Reading the monitor** (`run_accuracy_monitor.py`): it prints baseline vs recent APPLY precision (with
95% Wilson CI + `n_apply`), ECE, and base rate. A drift alert fires **only on a real departure** — the
recent CI must clear below baseline (not merely a lower point estimate), so ordinary small-sample noise
does not trip it. Tunable: `--window 60` (recent listings tested), `--ece-tolerance 0.03`,
`--min-window 20`.

---

## 2. The recalibration ritual — quarterly, and after a regime shift

**When:** every quarter (the heartbeat flags the calibrator `STALE` after 120 days), and whenever the
market regime shifts materially or the drift monitor alerts. Recalibration needs **new labelled
listings** in the backfill to be meaningful — refresh the data first.

**The discipline (do not shortcut this):**
1. A re-fit is only trustworthy if it is **deterministic** — a dry run must reproduce the current
   calibrator before you trust the pipeline.
2. `run_calibrate.py` sets the calibrator's gate flag to **`true` only if the reliability gate passes**.
   If the gate fails, the produced calibrator carries `passes_reliability_gate: false` and the app
   **withholds probabilities** (shows the verdict + UNCALIBRATED banner) — it does not ship a bad number.
3. The script **writes `models/calibrator.json`**, but that is a *working-tree candidate*, not a
   deployment. **You promote it explicitly** by reviewing the git diff and committing — and it only
   reaches users after a **rebuild + reinstall** (§3). Nothing auto-swaps the shipped model.

**Steps:**

```
# 0. Refresh inputs (only if you have new data to add)
python scripts/run_backfill.py          # re-pull / extend data/backfill/mainboard_ipos.csv (official NSE)
python scripts/fetch_vix.py             # refresh data/backfill/vix.csv (append-only)

# 1. Confirm the pipeline is deterministic BEFORE re-fitting (writes nothing)
python scripts/run_recalibration_check.py     # must print: REPRODUCES — max delta 0.0

# 2. Fit + gate the calibrator (writes models/calibrator.json + docs/CALIBRATION.md)
python scripts/run_calibrate.py
#    → read the printed gate table. PASSED = the candidate may ship. NOT PASSED = do not promote;
#      the app will withhold probabilities until a passing calibrator exists.

# 3. Refresh the held-out reliability report the UI serves (writes models/reliability.json)
python scripts/run_reliability_export.py

# 4. Review + promote by hand
git diff models/ docs/CALIBRATION.md          # inspect the parameter + metric changes
#    Sanity: sample_size grew as expected; gate PASSED; metrics within bounds (AUC≥0.55, ECE≤0.10).
git add models/ docs/CALIBRATION.md && git commit -m "recalibrate: <date>, N=<n>"

# 5. Ship it to your running app: rebuild + reinstall (§3).
```

If step 1 prints **MISMATCH** even before you add data, the shipped calibrator has drifted from the
current code/data — investigate that first (it usually means `models/calibrator.json` was hand-edited
or a feature-construction file changed without a recalibration).

---

## 3. Rebuild & repackage the app (also fixes a stale bundled calibrator)

The **source** always holds the current calibrator (`models/calibrator.json`), but a *previously built*
engine binary bundles whatever calibrator was current **when it was frozen**. After any recalibration —
or if you ever find the installed app running an old model — **rebuild from source**.

```
# One command (needs Node/npm + the venv Python on PATH; Windows Developer Mode ON — see the guide):
python packaging/build_app.py
```

This runs, in order: icon → **PyInstaller freeze of the engine** (bundles the current
`config` / `models` / `nifty` / `vix`) → PWA `npm run build` → desktop `npm run dist` (electron-builder
NSIS) → `src/ipo/apps/desktop/release/IPO-Advisor-Setup-<version>.exe`.

**Always verify the built engine carries the current calibrator** before reinstalling:

```
# Compare the bundled calibrator to the committed one — sample_size and hash must match.
.venv\Scripts\python.exe -c "import json; b=json.load(open('packaging/dist/ipo-engine/_internal/models/calibrator.json')); s=json.load(open('models/calibrator.json')); print('bundled', b['meta']['sample_size'], b['meta']['feature_code_hash']); print('source ', s['meta']['sample_size'], s['meta']['feature_code_hash']); print('MATCH' if b==s else 'STALE — rebuild')"
```

Expected today: **`sample_size 358`, hash `d01815d61aec4d33`, MATCH.** If it reads `STALE`, the build
picked up an old tree — re-run `build_app.py` from a clean source checkout. Then reinstall the produced
`.exe`.

**Full rebuild/repackage reference** (signing, the Microsoft Store MSIX target, and the Windows-11
`makeappx` workaround): [`docs/GATE7_PACKAGING.md`](../docs/GATE7_PACKAGING.md) — kept standalone as the
authoritative packaging guide.

---

## 4. Expected WARN states — not defects

The heartbeat (§1) will routinely print **`WARN`** for the feeds below. These are **deliberate
consequences of the deferred forward-recorder decision** (see [PROJECT_LOG §2](../docs/PROJECT_LOG.md#2-phase-history-p0p7)),
**not** problems to chase:

- **`[STALE] Nifty series (nifty.csv)`** — the Nifty regime series is not on a standing recorder; it
  only feeds the **weight-0 cold flag**, so staleness never moves a probability. Refresh it if/when you
  want the cold flag evaluated against current index history.
- **`[STALE] holiday calendar — covered only through <year>`** — the NSE holiday set is hand-maintained
  from the official circular (published each December). Add the next year's holidays to
  `src/ipo/core/constants.py` when convenient; until then the calendar simply flags that it needs the
  new year.

Only **`ERROR — a required artifact is MISSING`** (a missing calibrator / reliability report / backfill
CSV) is a genuine fault and exits non-zero.

---

## 5. Data freshness & manual refresh (v3 BUG 1)

The app now tells the honest truth about how current its data is, and lets you force a pull.

- **The "Updated …" timestamp = the last *successful* NSE pull**, not the last time the UI talked to
  the local engine. It advances **only** when a live NSE fetch actually lands — never on app open,
  render, or a local read. It is served by the engine's **`GET /status`** endpoint and persisted in
  the per-user data dir as **`ingest_state.json`** (`last_success` / `last_attempt` /
  `last_attempt_ok`). This file self-heals — if it's missing or corrupt the engine starts "blank"
  and the first successful pull repopulates it; it is safe to delete.
- **Amber "Updated … · retrying"** (header chip and Settings → Last refresh) means the store is still
  being served but the **most recent NSE pull failed** — the data is genuinely stale and the engine
  is retrying. This is the intended honest signal, not a crash. If it persists for hours, NSE is
  unreachable from this machine (check connectivity / whether NSE has started blocking the IP).
- **Opening or returning to the window triggers a real NSE pull.** The desktop shell asks the engine
  to fetch via a parent-only stdin channel (the renderer stays read-only and the HTTP API stays
  GET-only — no order/mutation path is introduced). The engine **debounces** (≈15 s), so a burst of
  focus events coalesces into one polite pull.
- **"Refresh now"** (Settings) and the **header Refresh** control do a **real** pull, not a re-read of
  the possibly-stale store. In a browser/dev context with no desktop shell, Refresh honestly falls
  back to re-reading the engine and says so (a live pull needs the packaged app).

None of this touches the model: `/status`, the freshness store, and the refresh trigger are all
outside the scoring path (verdicts/probabilities are byte-identical — proven per branch).

## Appendix — kept operator scripts (what writes what)

| Script | Purpose | Writes |
|---|---|---|
| `scripts/run_ingest.py` | Ingestion pipeline (sources → merge → hygiene → store + labels) | the record store |
| `scripts/run_backfill.py` | Polite official-NSE backfill of the mainboard sample | `data/backfill/mainboard_ipos.csv` |
| `scripts/fetch_vix.py` | India VIX daily-close backfill (append-only) | `data/backfill/vix.csv` |
| `scripts/run_calibrate.py` | **Fit + gate** the calibrator (the recalibration ritual, §2) | `models/calibrator.json`, `docs/CALIBRATION.md` |
| `scripts/run_reliability_export.py` | Export the held-out OOS reliability the UI serves | `models/reliability.json` |
| `scripts/run_recalibration_check.py` | Dry-run: does a re-fit reproduce the shipped calibrator? | nothing (read-only) |
| `scripts/run_accuracy_monitor.py` | Drift monitor: recent window vs OOS baseline | nothing (prints; exit 1 on alert) |
| `scripts/run_t3_stability.py` | T+3 settlement cross-break calibration check | `docs/T3_STABILITY.md` |
| `scripts/run_heartbeat.py` | Data-source freshness heartbeat | nothing (prints; exit 1 if missing) |

*These are the only scripts retained at project close — the one-shot evidence-generators that produced
the (now-consolidated) gate docs were removed; their results live permanently in
[`docs/PROJECT_LOG.md`](../docs/PROJECT_LOG.md).*
