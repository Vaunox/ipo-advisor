# GATE 7 — Packaging (the installable Windows app)

Phase 7 closes with a real Windows installer that installs like genuine software, launches the
bundled engine behind a readiness gate, and shows live verdicts — honoring all five invariants.

## Build

One command (needs Node/npm + the venv Python on PATH):

```
python packaging/build_app.py
```

which runs, in order:

1. `packaging/make_icon.py` → `src/ipo/apps/desktop/build/icon.ico` (branded diamond mark)
2. `packaging/build_engine.py` → `packaging/dist/ipo-engine/` — PyInstaller freezes the FastAPI
   engine into `ipo-engine.exe`, bundling **config, models (calibrator + held-out reliability),
   the Nifty regime series, and a curated demo store** (`_seed/`)
3. PWA `npm run build` → `src/ipo/apps/pwa/dist/`
4. desktop `npm run dist` (electron-builder, NSIS) →
   `src/ipo/apps/desktop/release/IPO-Advisor-Setup-0.7.0.exe`

The engine binary and the PWA are pulled into the app as electron-builder `extraResources`, so the
installer (~126 MB) is fully self-contained — no Python, Node, or model files required on the
target machine.

### Runtime data & paths

- **Read-only artifacts** (config/models/nifty/seed) resolve from the PyInstaller bundle
  (`sys._MEIPASS`) when frozen, the repo root in dev — via `runner._resource_root()`. Bundling the
  **config** is load-bearing: without it, feature weights fall back to empty and verdicts silently
  change (caught during S18 verification).
- **Writable data** (record store + verdict-transition log) lives under the per-user app-data dir
  (`%APPDATA%/IPO Advisor/engine-data`); Program Files is read-only. On first launch the engine
  copies the bundled demo store in (never overwriting existing user data).

## What the shell does (Electron)

- Free-port sidecar spawn → `/health` readiness gate (splash steps tick through the real stages) →
  only then loads the dashboard. Clean teardown on every exit path (no orphaned Python).
- System tray (Open / Restart engine / Quit); **minimize-to-tray** keeps the engine warm.
- **Remembered window state** (bounds + maximized) in `settings.json`.
- **Startup toggles** (launch-on-startup via `setLoginItemSettings`, minimize-to-tray, start
  minimized) over an advisory-only `ipoDesktop` IPC bridge; **Restart engine** kills + respawns
  the sidecar on the same port.
- **Native notifications** on a new APPLY crossing (Windows AppUserModelId set), adopting existing
  crossings silently on first run.

## Verification status

Automated here (reproducible):

- ✅ Frozen engine runs standalone: `/health` green (~1 s), first-run provisioning writes the
  store, `/board` returns the correct 10 verdicts (zomato/nykaa APPLY, SKIP cluster, tatatech
  kill-override), `/transitions` = 6 with no cycle-time flips — **byte-for-byte consistent with the
  from-source engine** (Invariant 1 survives packaging).
- ✅ Installer builds end-to-end (NSIS, 126 MB); the packaged tree contains `IPO Advisor.exe`,
  `resources/engine/ipo-engine.exe` (+ bundled config/models/_seed), `resources/pwa/`, and the icon.
- ✅ The **shipped** engine binary (inside `win-unpacked`) serves the board + provisions.
- ✅ Backend suite (211) green; PWA + desktop TypeScript compile.

Needs a manual GUI run (not automatable in this environment):

- ⬜ Run the installer → installs to Program Files, desktop + Start-menu shortcuts, uninstaller in
  Add/Remove Programs.
- ⬜ Launch → splash → dashboard with live verdicts; tray minimize/restore/restart/quit; window
  state remembered across launches; a native toast on a live APPLY crossing; launch-on-startup.

## Notes for the operator

- **Signing.** The app ships **unsigned** via a no-op `win.sign` hook (`sign-noop.cjs`) — the
  branded icon is still embedded (rcedit runs), but no certificate is used. The operator signs the
  installer + binaries with their own certificate: remove the hook in `package.json` and configure
  real signing. Claude never holds signing keys.
- **Developer Mode required to build.** electron-builder extracts a `winCodeSign` cache that
  contains macOS symlinks; creating them needs the symlink privilege, which **Windows Developer
  Mode** grants (Settings → System → For developers → Developer Mode → On). Enable it once (or build
  from an Administrator terminal). With it off, the installer build fails at
  "Cannot create symbolic link". This is an OS setting, unrelated to our build config.
