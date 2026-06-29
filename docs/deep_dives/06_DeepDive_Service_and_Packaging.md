# Deep Dive #6 — Advisory Service & Cross-Platform Packaging

*The runtime that keeps verdicts fresh and pushes them out, and the two packagings of one dashboard — a Windows `.exe` and an Android APK — that make this the "does everything" app. Reuses the FastAPI + PWA + PyInstaller + APK-wrap pattern from the hardware-monitor project. Grounded June 2026.*

---

## The shape: one brain, one UI, two packagings

```
   FastAPI service (the brain)
   ├─ scheduler  → ingest + score on a cadence, persist verdicts
   ├─ REST API   → /ipos, /ipo/{id}, /verdict/{id}, /health
   └─ notifier   → push when a verdict crosses a threshold
        │  serves
        ▼
   one PWA dashboard
        ├─ packaged as Windows .exe  (PyInstaller bundles service + PWA + webview)
        └─ packaged as Android APK   (web assets wrapped, points at the service)
```

The dashboard is written **once**. The desktop build runs the whole pipeline locally; the mobile build is a thin client of the operator's running service. No UI is written twice.

---

## Module A — The scheduler

IPO data moves on a clock, so the service polls on a cadence rather than on request:
- **Dense during open subscription windows** — e.g. every ~30 minutes, because GMP updates roughly that often during active hours.
- **Daily otherwise** — to pick up new RHP filings, anchor disclosures, and listing outcomes (to fill labels).
Each run is **idempotent** (Deep Dive #1): re-ingest, re-score, upsert verdicts. Scoring reads the persisted, versioned calibrator (Deep Dive #4); if no calibrated model is present, the service serves verdicts with the "uncalibrated" banner and **suppresses the probability**.

---

## Module B — The API

Small, read-only, stateless over the Parquet store + calibrator:
- `GET /ipos` — current and upcoming, with verdict badge + probability.
- `GET /ipo/{id}` — full record: verdict, calibrated probability, grounded reason, watch/kill flags, gross **and net-of-cost** listing-gain estimate, subscription + GMP timeline.
- `GET /verdict/{id}` — just the decision payload (for the notifier and mobile).
- `GET /health` — last successful ingest per source, calibrator version, staleness.
If the API is ever exposed beyond localhost, it is **authenticated and read-only** — it places no orders and holds no broker credentials (the system is advisory; both legs are manual).

---

## Module C — The notifier

Push when a verdict crosses a threshold ("StrongCo → APPLY, 72%"), with **dedupe** so the same verdict isn't re-sent every cycle (notify on *transitions*, not on every poll). Channels:
- **Telegram bot** — the pragmatic default (matches the equity system's alerting; trivial to stand up, works to phone without app-store friction).
- **Web push / FCM** — optional, for the installed apps.

---

## Module D — Windows `.exe` (PyInstaller)

Bundle the FastAPI service + the locally-served PWA + a lightweight webview shell (e.g. `pywebview`) into one self-contained desktop app that runs the entire pipeline offline-capable. Known gotchas to handle in the spec, not at runtime:
- **Hidden imports** — PyInstaller misses dynamically-imported modules (uvicorn workers, some scientific libs); declare them in the `.spec`.
- **Data files** — ship the PWA assets, default config, and the persisted calibrator via `--add-data`; resolve paths through `sys._MEIPASS`-aware helpers, never hardcoded relative paths.
- **One-file vs one-dir** — one-dir starts faster and is easier to debug; one-file is tidier to distribute. Default to one-dir for the operator build.
- **Antivirus false positives** — PyInstaller one-file binaries are sometimes flagged; document it and prefer one-dir if it bites.

---

## Module E — Android APK

Wrap the same PWA. Two routes:
- **TWA via Bubblewrap** — thinnest wrapper, but requires the PWA to be **hosted** with Digital Asset Links verification; the APK just opens the hosted PWA full-screen.
- **Capacitor** — bundles the web assets *inside* the APK and lets it call the operator's service endpoint over the network; more flexible (works without hosting the PWA at a verified domain) and gives a clean path to native push.

**Recommended: Capacitor** — bundle the dashboard, point it at the operator's running service (VPS or home machine), receive push. Signing uses the **operator's keystore, never Claude's**; the APK contains **no secrets** (it's a thin client of an authed API).

---

## Module F — Deployment topology (decide early)

Where does the brain run? It changes the build:

| Option | Service runs on | Apps point at | Best when |
|---|---|---|---|
| **Desktop-only** | the `.exe` on the PC | localhost / LAN | single-machine, no always-on push needed |
| **VPS** (recommended) | a small always-on server | the VPS endpoint | you want 24/7 windowed scheduling + push to phone |
| **Hybrid** | VPS for scheduling; `.exe` standalone too | either | flexibility; `.exe` works offline, VPS drives alerts |

The scheduler's value (catching GMP/subscription moves and firing timely alerts) is highest with an **always-on VPS**; the `.exe` remains a self-contained fallback that does everything locally on demand.

**Output contract of Layers 5–6:** a running, scheduled, alerting advisory service; an installable Windows `.exe` that runs the full pipeline; and a signed Android APK showing the same live verdicts with push — all read-only, order-free, advisory.

---

## Open questions to settle while building

- **Topology:** VPS (always-on, recommended) vs desktop-only vs hybrid.
- **APK route:** Capacitor (recommended, flexible) vs TWA (thinnest, needs hosted PWA).
- **Push channel:** Telegram (simplest) vs FCM/web-push (more native).
- **Auth:** if the service is exposed, the read-only API token scheme.

---

*This is an engineering/research reference, not financial advice. The service and apps are advisory only — they place no orders and hold no broker credentials; bidding and selling are done manually by the operator.*
