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
}

export interface AppSettings {
  bounds?: WindowBounds
  startup: StartupPrefs
}

export const DEFAULT_STARTUP: StartupPrefs = {
  launchOnStartup: false,
  minimizeToTray: true,
  startMinimized: false,
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
