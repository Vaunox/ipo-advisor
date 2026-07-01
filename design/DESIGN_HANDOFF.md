# Phase 7 — Locked Design Handoff

**Status: APPROVED** (design loop closed — operator said "lock in on this", 2026-07-01).
This is the fixed spec the build loop targets. The reference implementation is the interactive comp at
[`design/mockups/v1-terminal.html`](mockups/v1-terminal.html) — a single self-contained HTML/CSS/JS file.
The running app (PWA/React → Electron) must match it; the comp is the source of truth for look, states, and interactions.

Chosen direction: **"Terminal"** — dark-first (with light mode), verdict-forward, data-dense. Rationale: this is a fast
single-operator decision tool, so the verdict + its confidence dominate every screen, monospace figures keep dense data
scannable, and the terminal aesthetic suits keyboard-driven use.

> **Amendment (2026-07-01, build-loop decision):** the gross+net **gain estimate is shown for History/actuals only**.
> Live-IPO rows and the live detail **drop the forward gain cell** (the model predicts probability of a positive listing,
> not a magnitude) — probability is the live signal. Net-of-cost display still applies to History actuals. The comp's
> live-row gain figures are therefore illustrative-only and will not carry into the build.

---

## 1. Design tokens

Delivered as CSS variables in the comp; port verbatim to the React theme (CSS vars or a tokens file). Two themes via
`data-theme` on the root; a third "System" mode follows `prefers-color-scheme`.

### Color — dark (default)
| Token | Hex | Use |
|---|---|---|
| `--bg` | `#0a0d12` | app background |
| `--panel` | `#0f141b` | sidebar, cards, rows-on-hover |
| `--panel2` | `#141b24` | insets, meter tracks, active nav |
| `--line` | `#1e2732` | hairline dividers/borders |
| `--line2` | `#28323f` | stronger borders |
| `--tx` | `#e6ecf3` | primary text |
| `--tx2` | `#95a3b4` | secondary text |
| `--tx3` | `#5f6d7e` | muted/labels |
| `--accent` | `#5aa2ff` | interactive (sort active, links, focus) |

### Color — light
`--bg #eef1f5` · `--panel #ffffff` · `--panel2 #f6f8fb` · `--line #dde3ea` · `--line2 #cbd4de` ·
`--tx #0f172a` · `--tx2 #475569` · `--tx3 #8695a8` · `--accent #2563eb`

### Verdict colors (semantic — identical meaning in both themes; hues shift per theme)
| Verdict | dark text | light text | soft-bg (dark) |
|---|---|---|---|
| APPLY | `#3ddc84` | `#0f9d58` | `#0e2b1c` |
| MARGINAL | `#f5c451` | `#b7791f` | `#2e2610` |
| SKIP | `#ff5d63` | `#d63a3f` | `#2e1113` |
| INSUFFICIENT_SIGNAL | `#7c8aa0` | `#5b6b80` | `#1a222c` |

APPLY green also = positive gain / "hit". SKIP red also = negative / danger. MARGINAL amber also = caution/watch.

### Typography
- **Display / body / labels:** `Fira Sans` (300–700).
- **All figures, codes, timers, data:** `Fira Code` (monospace, `font-variant-numeric: tabular-nums`).
- Section labels: 10px, `letter-spacing .13–.14em`, uppercase, `--tx3`.

### Shape & spacing
- Radii: cards/panels **12px**, buttons/segments/pills **6–8px**, verdict tag **5px**, full-round for dots/switches.
- Card shadow: `0 1px 2px …/ 0 12px 30px -22px …` (subtler in dark, slightly stronger in light).
- Content padding: 20–26px. Row padding: 16px (compact density: 9px vertical).

---

## 2. Layout

```
┌────────────┬───────────────────────────────────────────────┐
│  sidebar   │  top bar: title/sub · [alerts][search][clock][theme] │
│  198px     ├───────────────────────────────────────────────┤
│  · brand   │  content (one section visible at a time)        │
│  · nav×4   │   Live · Upcoming · History · Settings · Detail  │
│  · status  │                                                 │
└────────────┴───────────────────────────────────────────────┘
```

- **Sidebar (198px, fixed):** brand mark; nav (Live signals / Upcoming / History / Settings) each with a count chip;
  footer status: `● Engine online` / `calibrator · gate passed` / `recalibrated N×` (N derived, see §6).
- **Top bar (sticky):** page title + subtitle (left); controls (right) = **alert bell** (unread badge), **Search** (`Ctrl K`),
  **IST clock** (12-hour, live), **theme toggle** (animated).
- **Tables:** header row + data rows are separate CSS grids that MUST share
  `grid-template-columns: minmax(0, …fr) …` so columns align exactly. (Plain `fr` = `minmax(auto,…)` causes per-grid
  drift — this was fixed and must not regress.)

---

## 3. Screens & components

### Live signals (default)
- Attention strip (dismissible ✕): "N IPOs close today — place bids before 17:00 IST · `Hh Mm` left" (live countdown).
- Sortable table (`Company · Verdict · Prob. · Grounded reason · Net gain`). Columns show a persistent `⇅`; active
  column shows solid `▲/▼` in accent. Default sort: Verdict. Sorting animates rows to new positions (FLIP).
- Row = pin **star** · company (name + sector · size · status) · **verdict badge** · **probability cell** ·
  grounded reason + **confidence meter** · **net-gain cell**. Row is clickable/`Enter` → detail. Pinned rows float to top.
  "CHANGED" badge when a verdict moved since last view.

### Verdict detail (opened from a row)
Back link → hero (verdict badge, name, meta, **reliability-gate chip**, big calibrated % ) → full-width
**calibrated-probability meter bar** → grounded reason + **"What drove this" contribution bars** (diverging ±) →
subscription (QIB/NII±sNII/bNII/Retail/Overall) + **progression sparkline** → watch items + kill-flags →
issue structure + **verdict-change log** (timeline) → **"What would change this call"** callout →
**net-of-cost breakdown** (gross → STT/DP/exch+GST → net) → cold-market caveat (only when cold) →
**Copy verdict as text** + advisory-only line → disclaimer footer. Jargon terms have hover tooltips.

### Upcoming
Calendar/watchlist (no verdicts — engine abstains pre-open). Columns: Company · Opens (countdown + anchor-day, "TOMORROW ★"
highlighted) · Structure preview · Valuation · **Notify** bell.

### History
Scorecard (IPOs scored · APPLY hit-rate actual vs predicted with mini bar · SKIPs avoided · calibration tracking) →
**reliability diagram** (bucketed predicted-vs-actual, diagonal + ±12pt band, per-bucket breakdown on the right) →
tools (search · verdict filter chips · **Export CSV**) → sortable table (Company · Verdict · Predicted · Actual ·
**Call**: ✓HIT / ✗MISS / ✓AVOIDED — misses shown honestly).

### Settings (operational only — never model internals)
Notifications · **Broker cost assumptions** (edit → recomputes net) · Appearance (theme · **density**) · Engine (status,
calibrator gate, last ingest, refresh/restart, preview-state toggles) · **Keyboard shortcuts** list · About + disclaimer.
**Hard boundary:** no thresholds/weights/calibration editable from the UI.

### Global
Command palette (`Ctrl K` / `/`) · alert center dropdown · **engine-unavailable** full-screen state · **startup splash**
(engine readiness gate: Starting engine → Health check → Loading calibrator → Ready) · toast.

---

## 4. States to build (not just the happy path)
- Verdict: **APPLY / MARGINAL / SKIP-by-kill-flag / INSUFFICIENT_SIGNAL** (last two show `—`, no number).
- **UNCALIBRATED** (reliability gate not passed): banner + every probability withheld app-wide. (Invariant #2.)
- **Cold-market caveat**: annotation only, never changes the number. (Invariant #3.)
- **Engine down**: full-screen "Engine unavailable" + retry; sidebar dot red.
- **Empty**: e.g. no history matches filter/search.

## 5. Interactions & motion
Row-entrance stagger · confidence bars grow (scaleX) · FLIP on sort · animated theme cross-fade + icon spin ·
keyboard: `Ctrl K`/`/` palette, `g l/u/h/s` nav, `t` theme, `?` shortcuts, `Esc` close · pin · density ·
copy-to-clipboard · CSV download · boot splash. All motion respects `prefers-reduced-motion`. Persisted to
localStorage: theme, density, cost settings, pins, alerts-read.

## 6. Honest / derived values (no fake constants in the shipped UI)
- **Port:** not shown as a fixed number — engine picks a free port at launch. UI reflects the runtime port (or "engine ready").
- **Recalibration count `N×`:** derived — `1` (first gate-passing fit, Q4 2024) `+ 1` per quarter since; increments itself.
  In the real app it comes from the calibrator's persisted version history (also captures ad-hoc regime-shift re-fits).
- All company names / subscription figures / dates in the comp are illustrative sample data.

---

## 7. Invariants the build MUST preserve (inherited from Phase 6)
1. **No recomputation** — UI shows the engine's verdict/probability verbatim (GET-only API). Sorting/filtering/search only reorder.
2. **Reliability gate holds** — UNCALIBRATED banner + no number when the calibrator hasn't passed.
3. **Calibration sacred** — cold caveat is annotation only; never moves the number.
4. **Advisory-only, structurally** — no order/buy/action control anywhere. (There is none in the comp, by design.)
5. **GMP is not a scoring input** and is not shown as one. (Absent from the comp entirely.)

---

## 8. Build loop — next steps (targets this spec)
1. **`apps/pwa/`** — React dashboard built to this design; port tokens/components; consume the existing GET-only API.
2. **`apps/desktop/`** — Electron shell; Python FastAPI engine as a **PyInstaller sidecar**: free-port selection,
   `/health` readiness gate before UI loads (the splash), clean teardown on every exit path, engine-down UI state.
3. **Packaging** — installer (Program Files, shortcuts, uninstaller), app icon, clean native window, system tray,
   native notifications on APPLY crossings, remembered window state → the installable Windows `.exe`.
4. **Gate 7** — `.exe` installs like real software, launches the bundled engine, shows live verdicts, fires native
   notifications, honors all five invariants. Tag `gate-7-app`.
