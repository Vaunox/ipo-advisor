// Persisted UI preferences (localStorage), mirroring the comp: theme (data-theme on the root,
// "system" follows prefers-color-scheme), density (a body class), pinned IPOs, last-seen verdicts
// (for the CHANGED badge), and broker cost assumptions (net-of-cost display).

import type { VerdictType } from '../api/types'

export type ThemeMode = 'dark' | 'light' | 'system'
export type Density = 'comfortable' | 'compact'
export interface Costs {
  stt: number
  dp: number
  oth: number
}
export interface Startup {
  launchOnStartup: boolean
  minimizeToTray: boolean
  startMinimized: boolean
}

const KEY = 'ipoadv'

interface Prefs {
  theme: ThemeMode
  density: Density
  pinned: string[]
  lastSeen: Record<string, VerdictType>
  costs: Costs
  startup: Startup
}

const DEFAULT_COSTS: Costs = { stt: 0.1, dp: 15.34, oth: 0.05 }
const DEFAULT_STARTUP: Startup = {
  launchOnStartup: false,
  minimizeToTray: true,
  startMinimized: false,
}

function load(): Prefs {
  try {
    const p = JSON.parse(localStorage.getItem(KEY) ?? '{}')
    return {
      theme: p.theme === 'light' || p.theme === 'system' ? p.theme : 'dark',
      density: p.density === 'compact' ? 'compact' : 'comfortable',
      pinned: Array.isArray(p.pinned) ? p.pinned : [],
      lastSeen: p.lastSeen && typeof p.lastSeen === 'object' ? p.lastSeen : {},
      costs: p.costs && typeof p.costs === 'object' ? { ...DEFAULT_COSTS, ...p.costs } : { ...DEFAULT_COSTS },
      startup:
        p.startup && typeof p.startup === 'object'
          ? { ...DEFAULT_STARTUP, ...p.startup }
          : { ...DEFAULT_STARTUP },
    }
  } catch {
    return {
      theme: 'dark',
      density: 'comfortable',
      pinned: [],
      lastSeen: {},
      costs: { ...DEFAULT_COSTS },
      startup: { ...DEFAULT_STARTUP },
    }
  }
}

let prefs = load()

function save() {
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs))
  } catch {
    /* ignore quota / disabled storage */
  }
}

/* ---- theme ---- */
export const getThemeMode = (): ThemeMode => prefs.theme
export function resolveTheme(mode: ThemeMode): 'dark' | 'light' {
  if (mode === 'system') return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  return mode
}
export function applyTheme(mode: ThemeMode, animate = false): void {
  const root = document.documentElement
  if (animate) {
    root.classList.add('theme-anim')
    window.setTimeout(() => root.classList.remove('theme-anim'), 520)
  }
  root.setAttribute('data-theme', resolveTheme(mode))
}
export function setThemeMode(mode: ThemeMode): void {
  prefs = { ...prefs, theme: mode }
  save()
  applyTheme(mode, true)
}

/* ---- density ---- */
export const getDensity = (): Density => prefs.density
export function applyDensity(density: Density = prefs.density): void {
  document.body.classList.toggle('compact', density === 'compact')
}
export function setDensity(density: Density): void {
  prefs = { ...prefs, density }
  save()
  applyDensity(density)
}

/* ---- pinned ---- */
export const getPinned = (): Set<string> => new Set(prefs.pinned)
export function togglePinned(id: string): Set<string> {
  const set = new Set(prefs.pinned)
  if (set.has(id)) set.delete(id)
  else set.add(id)
  prefs = { ...prefs, pinned: [...set] }
  save()
  return set
}

/* ---- last-seen verdicts (CHANGED badge) ---- */
export const getLastSeen = (): Record<string, VerdictType> => prefs.lastSeen
export function seedLastSeen(seed: Record<string, VerdictType>): void {
  if (Object.keys(prefs.lastSeen).length === 0) {
    prefs = { ...prefs, lastSeen: seed }
    save()
  }
}

/* ---- broker cost assumptions ---- */
export const getCosts = (): Costs => prefs.costs
export function setCosts(costs: Costs): void {
  prefs = { ...prefs, costs }
  save()
}

/* ---- startup & tray (applied by the desktop shell; persisted here) ---- */
export const getStartup = (): Startup => prefs.startup
export function setStartup(startup: Startup): void {
  prefs = { ...prefs, startup }
  save()
}
