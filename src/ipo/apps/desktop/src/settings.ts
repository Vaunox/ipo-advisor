// Main-process settings store: remembered window bounds + startup/tray preferences, persisted as
// JSON in the app's per-user data dir. The main process needs these at launch — before the
// renderer (and its localStorage) exists — to restore the window and honor start-minimized /
// launch-on-startup. Pure Node (no electron import) so it stays trivially testable.

import fs from 'node:fs'
import path from 'node:path'

export interface WindowBounds {
  x?: number
  y?: number
  width: number
  height: number
  maximized: boolean
}

export interface StartupPrefs {
  launchOnStartup: boolean
  minimizeToTray: boolean
  startMinimized: boolean
  // OP-1 internal bookkeeping (NOT a user toggle): set true after the one-time login-item marker
  // migration has run, so the app NEVER re-asserts auto-launch on later boots (a Windows
  // Task-Manager disable must stick). Undefined on a pre-OP-1 config; the migration sets it once.
  startupMigrated?: boolean
}

export interface AppSettings {
  bounds?: WindowBounds
  startup: StartupPrefs
  // UI/display preferences (theme, density, broker-cost display, notifications, pinned IPOs),
  // mirrored from the renderer so they persist in this config file rather than the fragile
  // file:// localStorage. `undefined` until first persisted — that lets the renderer migrate a
  // pre-existing localStorage config on upgrade instead of clobbering it with defaults. Every
  // field here is a display/OS pref: none is a scoring input (the engine owns verdicts).
  ui?: UiPrefs
}

export type ThemeMode = 'dark' | 'light' | 'system'
export type Density = 'comfortable' | 'compact'

export interface Costs {
  stt: number
  dp: number
  oth: number
}

export interface NotifPrefs {
  native: boolean
  applyCrossing: boolean
  anyChange: boolean
  quiet: boolean
}

export interface UiPrefs {
  theme: ThemeMode
  density: Density
  costs: Costs
  notifications: NotifPrefs
  pinned: string[]
  // v3 V3-14: whether the History "awaiting listing" card is collapsed. Durable so a fold survives
  // restart (localStorage under the shell's file:// origin does not reliably persist).
  awaitingCollapsed: boolean
  // v3 V3-16: whether the read-only debug console is enabled (the ` key toggles it when on). A dev
  // affordance, default OFF, durable so a fresh install ships off and the setting survives restart.
  devConsole: boolean
}

export const DEFAULT_STARTUP: StartupPrefs = {
  launchOnStartup: false,
  minimizeToTray: true,
  startMinimized: false,
}

// OP-1: distinguish a Windows auto-launch-at-login from a manual open. `getLoginItemSettings()
// .wasOpenedAtLogin` is macOS-only, so the robust Windows signal is a marker arg we register on the
// login item — Electron passes it in `process.argv` only when Windows auto-launches the app.
export const AUTOSTART_MARKER = '--ipoadvisor-autostart'

/** True when the app was auto-launched at system startup (the marker arg is present in argv). Pure,
 *  so `node --test` can exercise the argv-with/without-marker decision without a packaged app. */
export function wasAutoLaunched(argv: readonly string[]): boolean {
  return argv.includes(AUTOSTART_MARKER)
}

/** The login-item registration for the current prefs — ALWAYS carrying the marker so an auto-launch
 *  stays detectable. `openAtLogin:false` unregisters the item (the marker is then moot). */
export function loginItemSettings(startup: StartupPrefs): { openAtLogin: boolean; args: string[] } {
  return { openAtLogin: startup.launchOnStartup, args: [AUTOSTART_MARKER] }
}

/** One-time OP-1 migration decision (pure). Existing "launch on startup" users have a login item
 *  registered with NO marker; re-register it WITH the marker exactly once, then record it (via
 *  `next.startupMigrated`) so we NEVER re-assert on later boots — a Windows Task-Manager disable must
 *  stick. No-ops once migrated, and in dev (dev never registers a login item). */
export function planStartupMigration(
  startup: StartupPrefs,
  dev: boolean,
): { register: boolean; changed: boolean; next: StartupPrefs } {
  if (dev || startup.startupMigrated) return { register: false, changed: false, next: startup }
  return {
    register: startup.launchOnStartup,
    changed: true,
    next: { ...startup, startupMigrated: true },
  }
}

/** The window's intended visibility at boot — F1-rev's single end-state authority. Four outcomes:
 *  stay hidden in the tray, minimized on the taskbar, shown maximized, or shown at normal size. */
export type StartupWindowState =
  | 'hidden-to-tray'
  | 'minimized-to-taskbar'
  | 'shown-maximized'
  | 'shown-normal'

/** Decide the boot window state in ONE place (F1-rev). Start-minimized applies ONLY on a real
 *  auto-launch (the marker in argv, per `wasAutoLaunched`) AND when the user asked for it — a manual
 *  open always shows (the OP-1 invariant). Crucially, `savedMaximized` is folded into the SHOWN
 *  outcomes ONLY: it must NEVER pull a start-minimized launch into a visible state. The F1-rev bug was
 *  a SEPARATE code path (`win.maximize()` before `ready-to-show`) doing exactly that — `maximize()`
 *  "will also show … the window if it isn't being displayed" (Electron docs), so a restore-maximized
 *  concern silently pre-empted start-minimized. Centralising the decision here, with maximize deferred
 *  into the shown outcomes, closes that. "To the tray" also requires the tray to actually exist: if
 *  `createTray()` failed, degrade to the taskbar rather than hide into nothing with no way to reopen.
 *  Pure, so `node --test` fences all four outcomes + the degrade. */
export function startupWindowState(opts: {
  autoLaunched: boolean
  startMinimized: boolean
  minimizeToTray: boolean
  savedMaximized: boolean
  trayAvailable: boolean
}): StartupWindowState {
  if (opts.autoLaunched && opts.startMinimized) {
    if (opts.minimizeToTray && opts.trayAvailable) return 'hidden-to-tray'
    return 'minimized-to-taskbar' // tray off, OR tray creation failed → still reachable on the taskbar
  }
  return opts.savedMaximized ? 'shown-maximized' : 'shown-normal'
}

/** The BrowserWindow security posture in ONE lockable place (the "sealed shell" family: OP-6 + review
 *  #5). Context-isolated, no node integration, and — OP-6 — Chromium DevTools OFF in the packaged
 *  build (``dev=false`` makes ``Ctrl+Shift+I`` / the default-menu accelerator / ``openDevTools()`` all
 *  inert) and ON in dev. Unrelated to the V3-16 backtick console, which is a renderer React component
 *  + engine ``/logs`` fetch, a different layer entirely. Typed via the AMBIENT ``Electron.WebPreferences``
 *  (no runtime electron import — the type is erased), so this stays trivially testable under node --test. */
export function buildWebPreferences(
  dev: boolean,
  opts: { preload: string; engineBase: string },
): Electron.WebPreferences {
  return {
    preload: opts.preload,
    contextIsolation: true,
    nodeIntegration: false,
    additionalArguments: [`--engine-base=${opts.engineBase}`],
    devTools: dev,
  }
}

export const DEFAULT_COSTS: Costs = { stt: 0.1, dp: 15.34, oth: 0.05 }
export const DEFAULT_NOTIF: NotifPrefs = {
  native: true,
  applyCrossing: true,
  anyChange: false,
  quiet: true,
}

/** Coerce arbitrary JSON into a valid UiPrefs, falling back to defaults field-by-field (so a
 *  partial or hand-edited config file can never crash the load or smuggle in a bad value). */
export function normalizeUi(raw: unknown): UiPrefs {
  const u = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const costs = (u.costs && typeof u.costs === 'object' ? u.costs : {}) as Partial<Costs>
  const notif = (u.notifications && typeof u.notifications === 'object'
    ? u.notifications
    : {}) as Partial<NotifPrefs>
  return {
    theme: u.theme === 'light' || u.theme === 'system' ? u.theme : 'dark',
    density: u.density === 'compact' ? 'compact' : 'comfortable',
    costs: { ...DEFAULT_COSTS, ...costs },
    notifications: { ...DEFAULT_NOTIF, ...notif },
    pinned: Array.isArray(u.pinned) ? u.pinned.filter((x): x is string => typeof x === 'string') : [],
    awaitingCollapsed: u.awaitingCollapsed === true,
    devConsole: u.devConsole === true,
  }
}

function settingsFile(userDataDir: string): string {
  return path.join(userDataDir, 'settings.json')
}

/** Load settings from the user-data dir, falling back to defaults on any read/parse error. */
export function loadSettings(userDataDir: string): AppSettings {
  try {
    const raw = JSON.parse(fs.readFileSync(settingsFile(userDataDir), 'utf-8'))
    return {
      bounds: raw.bounds,
      startup: { ...DEFAULT_STARTUP, ...(raw.startup ?? {}) },
      ui: raw.ui ? normalizeUi(raw.ui) : undefined,
    }
  } catch {
    return { startup: { ...DEFAULT_STARTUP } }
  }
}

/** Persist settings ATOMICALLY (temp write → rename), best-effort. Mirrors saveSeenState (OP-3) and
 *  the durability cluster's tmp-then-os.replace idiom, so settings.json is never left torn by a crash
 *  mid-write (which loadSettings would otherwise degrade to defaults). Called from persistBounds
 *  (window move/resize) + the OP-1 boot migration, so not purely low-frequency. `fs.renameSync` is an
 *  atomic replace-over-existing on Windows (MoveFileExW REPLACE_EXISTING). A failed rename keeps the
 *  last-good file; the fixed `.tmp` is safe (main-process saveSettings calls are serialized). */
export function saveSettings(userDataDir: string, settings: AppSettings): void {
  try {
    fs.mkdirSync(userDataDir, { recursive: true })
    const target = settingsFile(userDataDir)
    const tmp = `${target}.tmp`
    fs.writeFileSync(tmp, JSON.stringify(settings, null, 2), 'utf-8')
    fs.renameSync(tmp, target)
  } catch {
    /* ignore — settings are a convenience, not correctness */
  }
}

// --- OP-3: the notification seen-sets, a SEPARATE durable store (seen-state.json) ------------------
// The bell's seen-sets (unread badge, native-toast dedup, the #8 CHANGED badge) were localStorage-only,
// which the shell's file:// origin does not persist across restart → the bell re-fired already-seen
// crossings. They live in their OWN file, NOT settings.json, ON PURPOSE: `notifiedCrossings` advances
// on every board update (high-frequency), and routing that through the config file would thrash the
// low-frequency deliberate-settings store. `lastSeen` values are opaque verdict strings here (the
// renderer owns the VerdictType enum). Bounding stays upstream (alerts.ts) — this only persists.

export interface SeenState {
  alertsSeen: string[]
  notifiedCrossings: string[]
  notifSeeded: boolean
  lastSeen: Record<string, string>
}

function seenStateFile(userDataDir: string): string {
  return path.join(userDataDir, 'seen-state.json')
}

/** Load the seen-sets. `null` when the file is ABSENT (not yet persisted → the renderer migrates its
 *  localStorage in); a defensively-parsed `SeenState` otherwise. A torn/corrupt file DEGRADES TO EMPTY
 *  (start-fresh) — never a crash on boot/hydration (worst case: one seen item re-shows next restart). */
export function loadSeenState(userDataDir: string): SeenState | null {
  const file = seenStateFile(userDataDir)
  if (!fs.existsSync(file)) return null
  try {
    const raw = JSON.parse(fs.readFileSync(file, 'utf-8'))
    return {
      alertsSeen: Array.isArray(raw.alertsSeen) ? raw.alertsSeen : [],
      notifiedCrossings: Array.isArray(raw.notifiedCrossings) ? raw.notifiedCrossings : [],
      notifSeeded: raw.notifSeeded === true,
      lastSeen:
        raw.lastSeen && typeof raw.lastSeen === 'object' && !Array.isArray(raw.lastSeen)
          ? raw.lastSeen
          : {},
    }
  } catch {
    return { alertsSeen: [], notifiedCrossings: [], notifSeeded: false, lastSeen: {} }
  }
}

/** Persist the seen-sets ATOMICALLY (temp write → rename), best-effort. Atomic NOT for the
 *  concurrency reason electron-store's conf-atomically fork targets (the single-threaded main process
 *  serializes these sync IPC writes — there is no self-concurrent write) but because a torn NON-atomic
 *  write would reintroduce OP-3's own bug: writeFileSync truncates-then-writes, so a crash mid-write
 *  leaves a corrupt file → loadSeenState degrades to empty → the bell re-fires. `fs.renameSync` is an
 *  atomic replace-over-existing on Windows (MoveFileExW REPLACE_EXISTING), mirroring the durability
 *  cluster's tmp-then-os.replace idiom. A failed rename keeps the last-good file (never a torn target);
 *  the whole thing is swallowed (convenience bookkeeping) and self-heals next cycle. Fixed `.tmp` is
 *  safe given the serialized writes. */
export function saveSeenState(userDataDir: string, seen: SeenState): void {
  try {
    fs.mkdirSync(userDataDir, { recursive: true })
    const target = seenStateFile(userDataDir)
    const tmp = `${target}.tmp`
    fs.writeFileSync(tmp, JSON.stringify(seen), 'utf-8')
    fs.renameSync(tmp, target)
  } catch {
    /* ignore — seen-state is convenience bookkeeping, not correctness */
  }
}
