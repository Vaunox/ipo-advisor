# Phase 7 — Build Loop Plan (for review; no app code written yet)

Targets the locked design ([DESIGN_HANDOFF.md](DESIGN_HANDOFF.md)) and the running Phase-6 engine.
Reviewed before implementation per operator request. **Nothing here recomputes a verdict** — the front end is a
face on the GET-only API; every gap below is closed by *exposing what the engine already computed*, never by a second
scoring path in the UI.

---

## 0. The most important finding first — data gaps

The design shows more than today's API returns. Current API (`src/ipo/service/api.py`, all GET):

| Endpoint | Returns |
|---|---|
| `/health` | `{status}` |
| `/ipos` | `list[Verdict]` |
| `/verdict/{id}` | `Verdict` |
| `/ipo/{id}` | `{record: IPORecord, verdict: Verdict}` |

`Verdict` = `ipo_id, verdict, probability|null, reason, watch[], kill_flags[]`.
`IPORecord` has name/segment/band/lot/issue_size/ofs_fraction/dates/qib_sub/nii_sub/retail_sub/issue_pe/peer_median_pe/anchor_book/promoter_litigation/listing_open|close.

**Maps cleanly (no backend change):** verdict badge, probability (+ null→withheld), grounded reason, watch items,
kill-flags, company/sector/size/status, subscription QIB·NII·Retail, price band, lot, issue size, OFS fraction,
issue P/E vs peer median, and — for History — *actual* listing gain (`listing_open/close`).

**Needs read-only surfacing from the engine (invariant-safe — exposes existing computation):**
1. **Feature contributions** ("What drove this" bars) — the scorer computes per-feature contributions; not in `Verdict`.
   → add to `/ipo/{id}` (e.g. `contributions: {feature, value, contribution}[]`) or a `/verdict/{id}/explain`.
2. **`anchor_quality`, `market_regime`, `book_closed`, `flags`** (drive the anchor score + **cold-market caveat**) — live in
   `IPOFeatures`, not surfaced. → include `features` in `/ipo/{id}`.
3. **Reliability report** (History scorecard + reliability diagram buckets) — produced by `calibration/reliability.py`.
   → serve the persisted report (new `/calibration` read endpoint or bundle the JSON artifact).
4. **History dataset** (predicted-vs-actual per past IPO) — the labelled backtest set. → read-only `/history`.
5. **Verdict-change log** (detail timeline + alert center) — requires the scheduler/notifier to *persist* verdict
   transitions. If not already stored, this is small Phase-6-side work. → `/ipo/{id}/transitions` + `/alerts`.

**One genuine product decision (not just plumbing):**
6. **Gross listing-gain magnitude.** The model outputs a *probability of a positive listing*, not a magnitude (GMP is
   explicitly "poor for magnitude"). The design shows a **gross + net** gain estimate. Net-of-cost is a legitimate UI
   display calc (gross − STT/DP/exchange/GST). **But the gross number must originate in the engine** — the UI inventing
   a magnitude would be a second scoring path (breaks Invariant 1). Options to decide:
   - (a) engine exposes a defined expected-gross estimate (new, and magnitude is admittedly unreliable);
   - (b) show gain **only in History** (actuals are known) and drop the forward magnitude on live rows, keeping
     probability as the live signal; or
   - (c) a clearly-labelled peer/heuristic band the engine computes.
   **DECIDED (2026-07-01): (b) History-only.** Live rows/detail drop the forward gross+net cell and lead with the
   probability; gross+net (net-of-cost) shows only where the listing actually happened (History).

> These are the right things to settle now. 1–5 are safe read-only extensions; 6 needs your decision.

---

## 1. Stack

- **Front end:** Vite + **React 18 + TypeScript**. Plain CSS with the comp's CSS-variable tokens (no Tailwind/UI kit —
  the comp is already hand-tuned; porting 1:1 is faster and keeps the exact look). `@tanstack/react-query` for GET
  fetching/caching. Small router (or state-based views like the comp). Fonts self-hosted (Fira Code / Fira Sans) for
  offline desktop use.
- **Shell:** **Electron** (locked decision) + `electron-builder`. Engine as a **PyInstaller** one-file sidecar.
- **Why not reuse the HTML comp as-is:** blueprint specifies a React PWA (`apps/pwa/`); React gives typed API models,
  real state, and testability. The comp becomes the pixel reference + a component-extraction source.

## 2. Layout

```
src/ipo/apps/
├── pwa/                      # React front end
│   ├── index.html  vite.config.ts  tsconfig.json  package.json
│   ├── public/fonts/…        # self-hosted Fira
│   └── src/
│       ├── main.tsx  App.tsx  theme.css (ported tokens)
│       ├── api/           client.ts  types.ts  hooks.ts   # GET-only
│       ├── state/         prefs.ts (theme/density/pins/alerts → localStorage)
│       ├── components/    Sidebar, TopBar, Clock, ThemeToggle, AlertCenter,
│       │                  CommandPalette, VerdictBadge, ConfidenceMeter,
│       │                  Toast, Splash, EngineDown, UncalibratedBanner …
│       └── screens/       Live/ Upcoming/ History/ Settings/ Detail/
├── desktop/                  # Electron shell
│   ├── package.json  electron-builder.yml
│   ├── src/ main.ts  preload.ts  sidecar.ts  window-state.ts  tray.ts
│   └── build/ icon.ico …
└── (android/  → DELETE — .exe-only decision)
```

## 3. Front-end architecture
- **Types** (`api/types.ts`) generated from the Pydantic models: `VerdictType` union, `Verdict`, `IPORecord`,
  `IPOFeatures`, plus the new `Contribution`, `ReliabilityReport`, `HistoryRow` once surfaced.
- **Data** (`api/hooks.ts`): `useVerdicts()`→`/ipos`, `useIpo(id)`→`/ipo/{id}`, `useHistory()`, `useCalibration()`,
  `useHealth()`. Read-only; no mutations exist. `probability===null` renders the withheld/UNCALIBRATED path.
- **Prefs** (`state/prefs.ts`): theme (dark/light/system), density, pins, alerts-read, cost assumptions — localStorage,
  same keys as the comp.
- **Screens** map 1:1 to §3 of the handoff. Cross-cutting: `UncalibratedBanner` (hides all probabilities when the gate
  is unpassed), `EngineDown`, `Splash`, `CommandPalette`, `AlertCenter`.
- **Invariant guards in code:** a single `Probability` component is the *only* place a number renders, and it renders
  `—` when `probability==null` — structurally impossible to show an unblessed number. No component computes a verdict or
  a probability. Cost math lives in one `netOfCost(gross, costs)` display util.

## 4. Electron shell — sidecar lifecycle (build-critical; get right in the first build)
- **Free port:** `sidecar.ts` asks the OS for a free port (or `:0`), passes it to the PyInstaller engine
  (`--port`) and to the renderer (via `preload` contextBridge). No hardcoded port.
- **Readiness gate:** spawn engine → poll `GET /health` until ok (timeout+backoff) → *only then* load/enable the UI.
  The **startup splash** is this gate made visible. Loading the UI first is the cold-start race we must avoid.
- **Teardown on every exit path:** track child PID; kill on `before-quit`, `will-quit`, window-all-closed, `SIGINT`,
  and on unexpected shell exit. Verify **no orphaned python** after repeated launch/quit (the classic bug).
- **Engine-down state:** if spawn fails or the child dies mid-session, renderer shows the `EngineDown` screen (already
  designed) via IPC; offer retry (re-spawn).
- **preload.ts:** contextBridge exposes `{ enginePort, onEngineStatus, notify, windowState }` — no Node in the renderer.

## 5. Packaging → genuine software
- `electron-builder` (NSIS): Program Files install, Start-Menu + desktop shortcuts, registered uninstaller (Add/Remove
  Programs). App **icon** (`.ico`) + window identity (title/taskbar). **Clean native window** (no browser chrome).
  **System tray** + **native OS notifications** (Phase-6 notifier → real Windows notifications on an APPLY crossing).
  **Remembered window size/position** (`window-state.ts`). Optional launch-on-startup. Note the **auto-update** path
  (electron-updater) even if deferred. Bundle the PyInstaller engine as an `extraResource`.

## 6. Build sequence (each step ends green: lint + types + tests)
1. **Settle §0 gaps** — decide #6; implement read-only API additions 1–5 (small, tested, invariant-safe).
2. **Scaffold `apps/pwa`** — Vite+React+TS, tokens/theme, fonts, App shell + routing, health/prefs plumbing. Delete `android/`.
3. **Live + Detail** against `/ipos` + `/ipo/{id}` (incl. UNCALIBRATED + engine-down states).
4. **Upcoming + History** (+ reliability diagram, CSV, filters) against the new endpoints.
5. **Settings + global** (command palette, alerts, splash, toasts, tooltips, shortcuts).
6. **Electron shell** — sidecar lifecycle (§4); PyInstaller build of the engine; dev + prod wiring.
7. **Packaging** (§5) → installable `.exe`.
8. **Gate 7** — see below. Tag `gate-7-app`.

## 7. Gate 7 checklist
`.exe` installs like real software (Program Files, shortcuts, uninstaller) · launches the bundled engine · **cold start
never shows UI before `/health` is green** · shows live verdicts · fires native notification on an APPLY crossing ·
**no orphaned python after repeated launch/quit** · honors all five invariants (no recomputation · reliability gate holds ·
cold caveat annotation-only · advisory-only/no order control · GMP absent).

## 8. Decisions (resolved 2026-07-01)
- **#6 gain magnitude → History/actuals only.** Live rows drop the forward gain cell and lead with probability; gross+net
  (net-of-cost) shows only in History. Handoff amended.
- **Auto-update → wired now** (electron-updater; feed URL TBD — GitHub Releases or a static host you choose).
- **App icon → generated** from the comp's ◆ mark (none supplied).
- **Code signing → config prepared; the operator signs, never Claude.** `.exe` ships **unsigned by default** (SmartScreen
  warning on first run). I wire the `electron-builder` signing config + a one-command sign step, but **I will not hold or
  use signing keys or sign on anyone's behalf** — explicit Ground Rule + key hygiene. You run the sign step with your
  certificate (or a local/CI secret you control); your key never touches me or the repo.

## 9. Risks
PyInstaller + FastAPI bundling quirks (hidden imports) · Windows notification/tray edge cases · sidecar orphan bugs
(mitigated by §4) · bundle size ~150 MB (accepted tradeoff). All are known-path per Deep Dive #6, Module D.
