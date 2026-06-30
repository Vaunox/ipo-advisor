# Deep Dive #6 — Advisory Service & Desktop Packaging

*The runtime that keeps verdicts fresh and pushes them out — the FastAPI engine (scheduler + read-only API + notifier) — and how it is packaged **inside the Windows `.exe`** as a sidecar. The app's UI, native shell choice, and Figma design loop are their own reference (Deep Dive #7). The `.exe` is **genuine native desktop software** (Discord/Steam class), not a webview. Grounded June 2026.*

---

## The shape: one brain (the engine), one desktop app

```
   FastAPI engine (the brain) — PyInstaller-built, runs as a sidecar process
   ├─ scheduler  → ingest + score on a cadence, persist verdicts
   ├─ REST API   → /ipos, /ipo/{id}, /verdict/{id}, /health   (read-only, GET-only)
   └─ notifier   → push when a verdict crosses into APPLY
        ▲  localhost HTTP
        │  (the Electron shell launches, health-checks, and shuts down the engine)
   Windows .exe = native shell (Electron) + bundled engine sidecar
```

The engine is **unchanged** by packaging — the shell is the front end + lifecycle manager, not a second brain. No scoring logic lives in the shell; no order/action path exists anywhere; the system is advisory. The app's UI + the Figma design loop are **Deep Dive #7**.

---

## Module A — The scheduler

IPO data moves on a clock, so the service polls on a cadence rather than on request:
- **Dense during open subscription windows** — e.g. every ~30 minutes, because subscription demand moves through active hours (and verdicts can flip).
- **Daily otherwise** — to pick up new RHP filings, anchor disclosures, and listing outcomes (to fill labels).
Each run is **idempotent** (Deep Dive #1): re-ingest, re-score, upsert verdicts. Scoring reads the persisted, versioned calibrator (Deep Dive #4); if no calibrated model is present, the service serves verdicts with the "uncalibrated" banner and **suppresses the probability**.

---

## Module B — The API

Small, read-only, stateless over the Parquet store + calibrator:
- `GET /ipos` — current and upcoming, with verdict badge + probability.
- `GET /ipo/{id}` — full record: verdict, calibrated probability, grounded reason, watch/kill flags, gross **and net-of-cost** listing-gain estimate, subscription timeline. (GMP is **not** a scoring input — it failed its Phase-5 gate, Deep Dive #5 — so it is not surfaced as one.)
- `GET /verdict/{id}` — just the decision payload (for the notifier and the app).
- `GET /health` — last successful ingest per source, calibrator version, staleness.
If the API is ever exposed beyond localhost, it is **authenticated and read-only** — it places no orders and holds no broker credentials (the system is advisory; both legs are manual).

---

## Module C — The notifier

Push when a verdict crosses **into APPLY** ("StrongCo → APPLY, 72%"), with **dedupe** so the same verdict isn't re-sent every cycle (notify on *transitions*, not on every poll). Channels:
- **Native OS notifications** — the desktop default: the Phase-6 notifier surfaces as real Windows notifications through the app's tray/shell (Deep Dive #7).
- **Telegram / web push** — optional, for an off-machine path (e.g. when the engine runs on a VPS).

---

## Module D — Windows `.exe` (genuine native software, Electron)

The `.exe` is **real desktop software** — Discord/Steam/VS Code-class — not a webview wrapper. Two parts: the **Python engine** packaged as a sidecar, and the **Electron** shell that hosts the UI and manages the engine. (The UI itself + the Figma design loop are **Deep Dive #7**.)

### The engine sidecar (PyInstaller)
The FastAPI engine (`service/runner.py` → `service/api.py`) is built into a standalone binary with **PyInstaller** and bundled inside the app; the shell spawns it as a child process. `.spec` gotchas:
- **Hidden imports** — declare uvicorn workers / dynamically-imported libs PyInstaller misses.
- **Data files** — ship the default config, the persisted calibrator (`models/calibrator.json`), and the Nifty series via `--add-data`; resolve paths through `sys._MEIPASS`-aware helpers.
- **One-dir** (not one-file) — faster start, fewer antivirus false positives.

### The shell — **Electron (the decision, from the start — not Tauri)**
For an AI-built app bolting a Python FastAPI sidecar under a native shell, the deciding factor is **build-path certainty and troubleshooting depth, not footprint**:
- **No new language toolchain.** Electron is Node-only; Tauri adds a **Rust** chain that compounds the already-novel sidecar wiring.
- **Deepest Python-sidecar ecosystem + prior art** — `child_process.spawn` + `electron-builder` + `electron-updater` are the most-trodden path for exactly "spawn a bundled binary and manage it."
- **Most-proven** — VS Code / Slack / Discord class.
- **Accepted tradeoff:** the ~150 MB bundle (ships its own Chromium) — a non-issue for a single-operator desktop app installed once.
- Tauri's purpose-built `externalBin` sidecar API and few-MB footprint are **genuinely nicer**, but are optimizations **consciously declined in favor of certainty**.

### Sidecar lifecycle (the shell manages the engine)
1. **On launch** — the shell `spawn`s the bundled engine sidecar on a free localhost port (uvicorn).
2. **Health-check** — poll `GET /health` until ready (timeout + a "starting…" state), then load the PWA at `http://127.0.0.1:<port>`.
3. **On quit** — terminate the sidecar cleanly (restart on crash). No orphaned Python process.

### Genuine-software requirements (Gate 7)
- **Installer** (NSIS via `electron-builder`): installs to **Program Files**, adds **Start Menu + desktop shortcuts**, registers an **uninstaller** in Add/Remove Programs (like Excel/Steam).
- **App icon** + window identity (title, taskbar icon).
- **Clean native window** — no browser chrome, no address bar.
- **System-tray** + **native OS notifications** on APPLY crossings.
- **Remembered window size/position**; optional **launch-on-startup**; an **auto-update** path (`electron-updater`) wired even if enabling is deferred.

### Advisory-only holds
The shell talks to the engine **only over the read-only, GET-only API**; no order/action path exists in the engine or the shell; the shell adds **no scoring logic**. The Python engine is the brain, unchanged.

---

## Module E — Deployment topology (decide early)

Where does the engine run? For v1 the `.exe` **bundles its own engine sidecar**, so the desktop app is self-contained. Topology only matters if you also want always-on, off-machine scheduling:

| Option | Engine runs in | Best when |
|---|---|---|
| **Desktop-only** (v1 default) | the bundled sidecar inside the `.exe` | single-machine; the app does everything locally on demand |
| **VPS** (optional) | a small always-on server | 24/7 windowed scheduling + push even when the PC is off |

The scheduler's value (catching subscription moves and firing timely alerts) is highest with an **always-on VPS**, but the self-contained `.exe` is the v1 deliverable.

**Output contract of Layer 5:** a running, scheduled, alerting advisory engine — read-only, order-free, advisory — that the Phase-7 desktop app consumes.

---

## Open questions to settle while building

- **Topology:** desktop-only (v1 default, self-contained) vs an optional always-on VPS for 24/7 push.
- **Push channel:** native OS notifications (the desktop default) vs Telegram/FCM if an off-machine path is added.
- **Auth:** if the engine is ever exposed beyond localhost, the read-only API token scheme.

---

*This is an engineering/research reference, not financial advice. The service and app are advisory only — they place no orders and hold no broker credentials; bidding and selling are done manually by the operator.*
