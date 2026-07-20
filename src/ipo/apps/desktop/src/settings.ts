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

/** Persist settings (best-effort; a write failure must never crash the app). */
export function saveSettings(userDataDir: string, settings: AppSettings): void {
  try {
    fs.mkdirSync(userDataDir, { recursive: true })
    fs.writeFileSync(settingsFile(userDataDir), JSON.stringify(settings, null, 2), 'utf-8')
  } catch {
    /* ignore — settings are a convenience, not correctness */
  }
}
