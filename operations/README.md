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
| **Data-source heartbeat** | `python scripts/run_heartbeat.py --data-dir <app data dir>` | Monthly, and before any recalibration | `OK` (all fresh) or `WARN` (expected stale feeds — see §4) | **`ERROR — a required artifact is MISSING`** (exit 1): `models/calibrator.json` / `reliability.json` / a `data/backfill/*.csv` is gone. Restore it. · **`ATTENTION — N listing(s) OVERDUE`** (exit 1, v3 finding-④): a book-closed IPO the Live→History resolution never completed — the symbol never matched in NSE past-issues, or its listing price never backfilled — so it is silently stranded under an "awaiting listing" label. Inspect the named IPO(s); see §5. `--data-dir` defaults to `data_store` (dev) — point it at the installed app's per-user `engine-data` dir to audit the real store. |
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

### Stranded listings — the overdue detector (v3 finding-④)

An IPO leaves Live and enters History once the engine stamps its `listing_date` (+ the listing-day
price) — `resolve_listings` does this by matching the closed issue against NSE's past-issues feed.
That match can **fail silently**: if NSE's symbol never matches the one we hold, the listing is never
stamped; if the bhavcopy price never backfills, the row is stamped but never priced. Either way the
IPO would otherwise sit forever under an "awaiting listing" label with nothing flagging it.

The app now **names the strand instead of hiding it.** Past the expected listing day + a
holiday-aware trading-day grace buffer, History's "Awaiting listing outcome" section shows the IPO as
**"listing overdue — resolution may have failed"** (or "…outcome overdue — price never recorded")
with an overdue count and a red badge, and the **heartbeat** (§1) prints an `[OVERDUE]` block and
exits non-zero — so a strand surfaces in the monthly ritual, not weeks later by noticing a badge.
**When it fires:** look the IPO up on NSE. If it *has* listed, the symbol we hold most likely differs
from NSE's past-issues symbol (fix the record / ingest mapping); if it genuinely hasn't listed yet,
the buffer clears it automatically once it does. The check is our-dates-only (no second data source),
so it stays truthful even when the Upstox context cache is stale or offline.

### The per-IPO Upstox context cache (v3 V3-5/V3-6+)

The **one** display-only Upstox cache feeds every per-IPO context field the app shows: the
Allotment tab's **registrar** (V3-6, deep-links to the registrar's own allotment-check site — the
app never handles a PAN), the detail page's **RHP link** (V3-5) and **bid lot** (V3-8, shown as an
*indicative* "≈ N shares · approx ₹…" — NSE provides lot_size on 0% of IPOs, so Upstox is the sole
source and it's never presented as an exact reported figure), the detail page's **ISIN + industry**
reference fields (V3-11, plain display metadata, no source named), and later the anchor list (V3-10).
One cache, one refresh, one staleness rule. It is **not** fetched by the app — it's an
occasional, token-free cache you refresh:

```
# needs your Upstox Analytics Token in the environment (or research/.env): UPSTOX_TOKEN=...
python scripts/refresh_context.py --data-dir <the app's data dir>
#   dev: --data-dir data_store   ·   installed app: the per-user engine-data dir the shell passes
```

- These fields are **fixed once filed and never change**, so this is occasional reference data —
  run it when new IPOs appear (like `run_backfill`), not on a cadence. It queries open+closed+listed
  (the RHP first appears at `open`).
- It writes `<data_dir>/context/ipo_context.json` (token-free, safe to share/commit/sync).
- **Degrades honestly:** a missing cache → the surface says "not loaded"; a per-IPO absence
  distinguishes "not yet published/filed" from **"cache is stale"** (the cache predates the IPO) —
  it never shows a stale value as current. Symbol-less (`'NONE'`) upcoming IPOs are excluded at
  ingest.
- **Severable & non-model:** the app only reads this cache; if Upstox is down you simply can't
  refresh — verdicts, probabilities, and live signals are entirely unaffected. Context data lives in
  a store separate from the model and can never become a scoring input (transitively import-graph
  proven: no `ipo.service.*` is reachable from the scoring path).
- **External links are host-allowlisted:** the app only opens pinned hosts — the eight registrar
  portals and the SEBI filing host (`sebi.gov.in`) for RHPs. An issuer-hosted RHP or any other URL
  renders as inert, copyable text, never a one-click open (a poisoned cache can't redirect the user
  to an attacker page).
- The script is **VM-runnable as-is** (pure Python + `requests`, no desktop assumptions): when the
  Part-II VM data layer lands it adopts this script unchanged as the VM-primary refresher, with
  local execution as the fallback — the same VM-primary/local-fallback discipline as every feed.

### The VM data plane (v3 V3-1) — off by default (ships dark)

The app can read its two data stores (the NSE record store and the Upstox context cache) from a **VM
read-API** instead of scraping locally — VM-primary, with an **honest local fallback**. It is **off by
default**: with no `VM_BASE_URL` set the engine runs exactly as before the VM existed (pure local
scrape, no indicator), so every build ships dark until you deploy the VM.

- **Enable it** by setting one variable in the engine's environment:
  ```
  VM_BASE_URL=http://<vm-host>:<port>   # the VM read-API base — GET-only: /health, /records, /context
  ```
  Read directly by the runner, deliberately **not** an `IPO_*` key, so VM wiring can never leak into
  the model config.
- **Behavior:** each refresh pulls both stores from the VM; on any failure (unreachable, non-200,
  malformed/truncated envelope, timeout — 10s × 2 retries) that store falls back to local and the
  header sync chip says so honestly — **records** re-scrape fresh from NSE (still current), **context**
  keeps the last-known cache and ages (the Upstox token lives on the VM, so it can't self-refresh).
  Both stores from the VM → the chip stays quiet.
- **The VM side** is `scripts/run_vm_server.py --data-dir <vm-data> --host 0.0.0.0 --port <p>` —
  GET-only, serving whatever the VM's own fetch jobs (`run_ingest.py` + `refresh_context.py`, run **on**
  the VM) have written. It never runs the model, and the served data is public + token-free.
- **Read-only by construction:** the app can only READ from the VM — there is no mutation route in the
  read-API. The output half (app history → durable VM archive) is **V3-2**, and by design the **VM
  pulls** it (the app never pushes).

### Durable archive (v3 V3-2) — off by default; deploy runbook

The app's `verdict_transitions.json` (the one non-reproducible thing it holds — *when* each verdict
changed) is backed up to a **private git archive repo** the app can never corrupt: a local scheduled
task **drops** it outbound (git push), a VM timer **pulls → validates → append-merges** it into a
durable archive. Ships dark — nothing runs until the steps below. The SSH deploy key lives only in the
two schedulers' environments; **never commit it** (same posture as the Upstox token).

**One-time setup (you provision):**

1. **Create a private archive repo** — its own repo, NOT a branch of the code repo (operational data:
   separate lifecycle + sensitivity). An empty private repo is enough; note its SSH URL.
2. **Deploy key** — generate an SSH key, add the public half to the archive repo as a deploy key
   **with write access** (the drop pushes); keep the private half only in the two environments below.
   If your host supports it, protect the branch against force-push — then a compromised app can at
   worst *add* junk commits (which the VM validates away), never rewrite history.
3. **Clone the rendezvous on both machines** — desktop: `git clone <ssh-url> C:\ipo-archive`; VM:
   `git clone <ssh-url> /opt/ipo-archive`.

**App-side drop (desktop, daily via Task Scheduler).** Register a daily task; `-DataDir` is the
installed app's engine-data dir, `-Rendezvous` the desktop clone (the whole `/TR` value is one line):

```
schtasks /Create /TN "IPO Archive Drop" /SC DAILY /ST 20:30 /RL LIMITED /F /TR "powershell -ExecutionPolicy Bypass -NoProfile -File C:\path\to\scripts\archive_drop.ps1 -DataDir %APPDATA%\ipo-advisor-desktop\engine-data -Rendezvous C:\ipo-archive"
```

- The task's environment must expose the SSH key to `git` (a key under `%USERPROFILE%\.ssh` via
  ssh-agent, or `GIT_SSH_COMMAND` pointing at it). **The key is never in the repo.**
- Runs whether or not the app is open (it just reads the file + pushes). No `-Rendezvous`, or a
  non-git path → the script is a **silent no-op**, so it is safe to register before the repo exists.

**VM-side pull-merge (daily via systemd timer).** `/etc/systemd/system/ipo-archive-pull.service`:

```
[Service]
Type=oneshot
Environment=GIT_SSH_COMMAND=ssh -i /home/ipo/.ssh/archive_key -o IdentitiesOnly=yes
ExecStart=/usr/bin/git -C /opt/ipo-archive pull --ff-only
ExecStart=/opt/ipo/.venv/bin/python /opt/ipo/scripts/archive_pull.py --source /opt/ipo-archive/verdict_transitions.json --archive /opt/ipo/archive --records /opt/ipo-archive/ipo_records.parquet
```

`/etc/systemd/system/ipo-archive-pull.timer` → `[Timer] OnCalendar=*-*-* 21:00:00` + `Persistent=true`,
`[Install] WantedBy=timers.target`; enable with `systemctl enable --now ipo-archive-pull.timer`. A
malformed/truncated drop makes `archive_pull.py` **exit non-zero and merge nothing** (visible in
`journalctl -u ipo-archive-pull`); a healthy run logs `archive_pull_merged` to `<archive>/logs/pull.log`.

**Recovery** — to restore history on a fresh machine, copy `<archive>/verdict_transitions.json` from
the VM back into the app's engine-data dir (same shape). The rendezvous git history is a second,
independent backup of every drop.

### VM monitoring, heartbeat & keepalive (v3 V3-3) — off by default; deploy runbook

Two independent mechanisms keep the VM data plane visible and alive; each ships dark and stands alone.

**Primary — heartbeat-staleness detector (always on, can't-itself-fail).** The VM writes a small
`heartbeat.json` (last beat, ingest freshness, free disk, keepalive marker) each cycle and pushes it
to a git **heartbeat channel**; your desktop `run_heartbeat --vm-heartbeat <clone>/heartbeat.json`
reads it and **names any failure honestly** (`VM heartbeat - last beat 1d ago — the VM's fetch cycle
may have stopped`, `VM ingest - NSE fetch failing …`, `VM disk - 4% free …`) and **exits non-zero**.
This needs *nothing alive on the VM* at check time and *no VM credentials on the desktop* — it's a
git-history read. It carries essentially every failure mode; with no `--vm-heartbeat` it's inert.

**Backup — one out-of-band liveness ping.** For the single time-sensitive, unrecoverable case (Oracle
reclaiming the instance), `vm_heartbeat.py` pings a free dead-man's-switch monitor (`HC_PING_URL`,
e.g. healthchecks.io) each cycle; the monitor emails you when pings **stop**. One liveness bit, not an
alerting stack. No `HC_PING_URL` → no ping (dark).

**Deploy (you provision):**

1. **Heartbeat channel** — simplest: a dedicated `heartbeat` branch of the archive repo (reuses the
   key; a *different* branch from the drops, so the desktop-drop and VM-heartbeat pushes never race).
   Clone it on the VM; clone (or reuse) it on the desktop.
2. **Dead-man's-switch** — create a check on healthchecks.io (or ntfy/Telegram), expected ~daily; put
   its ping URL in the VM env as `HC_PING_URL`.
3. **VM systemd — heartbeat** (`oneshot`, after each ingest / daily): `Environment=HC_PING_URL=…`;
   `ExecStart=…/python …/scripts/vm_heartbeat.py --data-dir /opt/ipo/data --beat /opt/hb/heartbeat.json`;
   then `ExecStart=/usr/bin/git -C /opt/hb commit -am beat` and `ExecStart=/usr/bin/git -C /opt/hb push`.
4. **VM systemd — keepalive** (`nice`d timer, e.g. every 30 min): `ExecStart=…/python
   …/scripts/vm_keepalive.py --data-dir /opt/ipo/data --seconds 120`. **Tune + verify:** after a day,
   check the Oracle console CPU metric sits **above the reclaim bar over the window** (it averages, so
   a brief spike is not enough) — raise `--seconds`/frequency until it does. Steady genuine fetch load
   does most of the work; this is the top-up.
5. **Desktop** — before the heartbeat ritual, `git -C <hb-clone> pull`, then
   `run_heartbeat --vm-heartbeat <hb-clone>/heartbeat.json`.
6. **HARD calendar item — Oracle console login every ≤30 days.** No script can prevent *account*-level
   reclaim; this is a manual recurring reminder you set. It is load-bearing, not optional.

### Weekly fallback self-test (v3 V3-4) — off by default; deploy runbook

V3-1's local fallback only runs when the VM is down, so it can rot undiscovered until the day you need
it. This self-test drives the **genuine** local path on demand (only the trigger is faked — a
`VmClient` that raises `VmUnavailable` — while `refresh_from_nse` → the real `NseClient` → real NSE →
validation → write is all genuine) into a **throwaway, always-cleaned-up** store, and records a
verdict `run_heartbeat` surfaces. No manufactured outage; the VM can be up and serving.

1. **Weekly scheduled task (desktop, repo `.venv` Python).** It uses the SAME polite `NseClient` as
   the live ingest (rate limit + UA — one hit a week is trivial load):
   ```
   schtasks /Create /TN "IPO Fallback Selftest" /SC WEEKLY /D SUN /ST 09:00 /RL LIMITED /F /TR "C:\path\to\.venv\Scripts\python.exe C:\path\to\scripts\fallback_selftest.py --out C:\path\to\data_store\fallback_selftest.json"
   ```
2. **Ritual.** Add `--fallback-selftest <path>/fallback_selftest.json` to your `run_heartbeat` run. A
   FAILED scrape (feed-shape change / broken dependency) → `[STALE] local fallback - self-test FAILED
   …` and exit 1; a stale result (the weekly task stopped) → `… self-test stale … weekly test not
   running?` and exit 1; healthy → `[OK] local fallback - self-test passed 3d ago (7 records)`. Off
   unless the flag is given — ships dark.

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
| `scripts/run_heartbeat.py` | Data-source freshness heartbeat **+ stranded-listing audit** (`--data-dir`, v3 finding-④) **+ VM-liveness check** (`--vm-heartbeat`, v3 V3-3) **+ fallback self-test verdict** (`--fallback-selftest`, v3 V3-4) | nothing (prints; exit 1 if a feed is missing, a listing is overdue, the VM heartbeat is stale/degraded, **or** the fallback self-test FAILED/stale) |
| `scripts/refresh_context.py` | v3 V3-5/6/8/11 — refresh the per-IPO Upstox context cache (registrar + RHP + lot_size + isin + industry; display-only; needs `UPSTOX_TOKEN`) | `<data_dir>/context/ipo_context.json` (token-free) |
| `scripts/run_vm_server.py` | v3 V3-1 — the VM read-API server (GET-only `/health` `/records` `/context`; run **on** the VM behind its fetch jobs; never runs the model) | `<data_dir>/logs/vm.log` (serves records + context read-only) |
| `scripts/archive_drop.ps1` | v3 V3-2 — app-side drop: push `verdict_transitions.json` (+ records) to the private archive rendezvous (outbound-only; dark-ship no-op if unconfigured) | commits to the rendezvous git clone |
| `scripts/archive_pull.py` | v3 V3-2 — VM-side pull-merge: validate + append-merge a drop into the durable archive (rejects malformed; idempotent) | `<archive>/verdict_transitions.json`, `<archive>/logs/pull.log` |
| `scripts/vm_heartbeat.py` | v3 V3-3 — VM-side: write the liveness heartbeat + ping the dead-man's-switch monitor (dark-ship without `HC_PING_URL`) | `<channel>/heartbeat.json`, `<data_dir>/logs/heartbeat.log` |
| `scripts/vm_keepalive.py` | v3 V3-3 — VM-side: bounded CPU keepalive (anti-reclaim) + touch the marker the heartbeat checks | `<data_dir>/keepalive.marker` |
| `scripts/fallback_selftest.py` | v3 V3-4 — weekly: drive the REAL local fallback (VM up) into a throwaway store + record the verdict; run_heartbeat surfaces FAILED/stale | `<out>/fallback_selftest.json` |

*These are the only scripts retained at project close — the one-shot evidence-generators that produced
the (now-consolidated) gate docs were removed; their results live permanently in
[`docs/PROJECT_LOG.md`](../docs/PROJECT_LOG.md).*

### Dev/CI note — STANDING RULE: every code/tool pin carries an upper bound

**Every dependency in `pyproject.toml` is pinned `>=X,<next-major` — the ONLY exception is a pure
data package (`tzdata`), where you want the latest.** Reason: an unbounded pin lets a routine
`pip install -e ".[dev]"` pull a new major that **silently reddens the gate on `main` with no code
change** — the same silent-failure class this project keeps guarding against (cf. §5 / finding-④). It
has bitten this project three times (unbounded-alert growth → **mypy 2.x** → **black 26.x**), so it is
now a rule, not a case-by-case fix. When you add a dependency, add its upper bound. To adopt a new
major, do it deliberately in one pass: bump the cap, run the full gate, fix what the new major flags
(mypy: annotate; black: `black .` + commit the reformat), then commit. Notable caps:

- **`mypy>=1.9,<2`** — mypy 2.x tightened bare-generic checks.
- **`black>=24.0,<27`** — black changes its stable style yearly (26.x reformatted `logging.py` +
  `refresh_context.py`).
- **`httpx>=0.27,<1.0`** — pinned until the starlette/httpx2 TestClient cutover is handled.

### Dev note — the scoring-path guard (Part I rule 1)

Every v3 change must leave the scoring path byte-identical. Two checks, run on each branch:
- **Cheap proxy:** `python scripts/check_scoring_path.py [base]` fails if a change touches anything
  under `model` / `calibration` / `features` / `core`, `models/`, or `config/` — with one reviewed
  allowlist entry, `src/ipo/core/logging.py` (a **write-only sink**, unreachable from
  `features/build.py`; verdicts proven byte-identical when it changes). The allowlist keeps the
  proxy *precise* — a guard that fires on a file it can't break trains you to override it, and then
  you override the real firing too. Add to it only with a reason.
- **Definitive:** dump verdicts on the branch vs the base and confirm **`MAX|Δprob| = 0.0`** across
  all IPOs. The proxy is a fast pre-check; this is the actual invariant.
