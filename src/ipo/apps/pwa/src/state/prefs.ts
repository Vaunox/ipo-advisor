// Persisted UI preferences (localStorage), mirroring the comp: theme (data-theme on the root,
// "system" follows prefers-color-scheme), density (a body class), pinned IPOs, last-seen verdicts
// (for the CHANGED badge), and broker cost assumptions (net-of-cost display).

import { useSyncExternalStore } from 'react'
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
export interface NotifPrefs {
  native: boolean
  applyCrossing: boolean
  anyChange: boolean
  quiet: boolean
}

const KEY = 'ipoadv'

interface Prefs {
  theme: ThemeMode
  density: Density
  pinned: string[]
  lastSeen: Record<string, VerdictType>
  costs: Costs
  startup: Startup
  notifications: NotifPrefs
  alertsSeen: string[]
  notifiedCrossings: string[]
  notifSeeded: boolean
  awaitingCollapsed: boolean
}

const DEFAULT_COSTS: Costs = { stt: 0.1, dp: 15.34, oth: 0.05 }
const DEFAULT_NOTIF: NotifPrefs = { native: true, applyCrossing: true, anyChange: false, quiet: true }
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
      notifications:
        p.notifications && typeof p.notifications === 'object'
          ? { ...DEFAULT_NOTIF, ...p.notifications }
          : { ...DEFAULT_NOTIF },
      alertsSeen: Array.isArray(p.alertsSeen) ? p.alertsSeen : [],
      notifiedCrossings: Array.isArray(p.notifiedCrossings) ? p.notifiedCrossings : [],
      notifSeeded: p.notifSeeded === true,
      awaitingCollapsed: p.awaitingCollapsed === true,
    }
  } catch {
    return {
      theme: 'dark',
      density: 'comfortable',
      pinned: [],
      lastSeen: {},
      costs: { ...DEFAULT_COSTS },
      startup: { ...DEFAULT_STARTUP },
      notifications: { ...DEFAULT_NOTIF },
      alertsSeen: [],
      notifiedCrossings: [],
      notifSeeded: false,
      awaitingCollapsed: false,
    }
  }
}

let prefs = load()

// A tiny subscribable store (v3 BUG 3). Consumers that must react to changes from *other* writers
// (theme — see useThemeMode) subscribe here instead of caching the value in local state; every
// persistence call (saveLocal, and save via it) fires notify(), so a change from any writer reaches
// every subscriber. Snapshots are primitives compared by value, so an unrelated change (e.g. costs)
// notifies theme subscribers but triggers no re-render.
const listeners = new Set<() => void>()
// Subscribe to any store change (returns an unsubscribe). Backs `useThemeMode`; exported so the
// store's notify contract is directly testable and available to future reactive hooks.
export function subscribe(cb: () => void): () => void {
  listeners.add(cb)
  return () => {
    listeners.delete(cb)
  }
}
function notify(): void {
  for (const l of listeners) l()
}

// Durable store: in the packaged desktop shell the source of truth is the app's config file
// (settings.json in the Electron user-data dir), reached over IPC via the preload bridge — because
// localStorage under the file:// origin the shell loads is not reliably persisted across restarts.
// In the browser / dev preview there is no bridge, so localStorage is the store. window.ipoDesktop
// is injected by apps/desktop/src/preload.ts.
interface UiPrefs {
  theme: ThemeMode
  density: Density
  costs: Costs
  notifications: NotifPrefs
  pinned: string[]
  awaitingCollapsed: boolean
}
interface DesktopBridge {
  getPrefs?: () => Promise<UiPrefs | null>
  setPrefs?: (ui: UiPrefs) => Promise<void>
}
const desktop: DesktopBridge | null =
  typeof window !== 'undefined' ? ((window as { ipoDesktop?: DesktopBridge }).ipoDesktop ?? null) : null

function uiSnapshot(): UiPrefs {
  return {
    theme: prefs.theme,
    density: prefs.density,
    costs: prefs.costs,
    notifications: prefs.notifications,
    pinned: prefs.pinned,
    awaitingCollapsed: prefs.awaitingCollapsed,
  }
}

// localStorage mirror only. Used by ephemeral view-state (last-seen verdicts, alert-read, native-
// notification dedup) and the startup mirror — bookkeeping that must never reach the durable config
// file (its durable home, for startup, is the separate startup:set IPC path).
function saveLocal() {
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs))
  } catch {
    /* ignore quota / disabled storage */
  }
  notify() // wake reactive consumers (useThemeMode) — every setter routes through here
}

// Durable save: the localStorage mirror PLUS a write-through to the app config file (desktop). Only
// the five durable UI settings (theme, density, costs, notifications, pinned) call this, so the
// config file holds genuinely durable preferences and incidental bookkeeping never rewrites it.
function save() {
  saveLocal()
  // Fire-and-forget — a failed IPC must never break the UI (the mirror above still holds).
  if (desktop?.setPrefs) void desktop.setPrefs(uiSnapshot())
}

/**
 * Desktop only: hydrate the in-memory prefs from the durable config file before first paint, so a
 * restart shows the saved settings rather than defaults. On first run after upgrade the config file
 * has no UI prefs yet (getPrefs resolves null); we then migrate the current localStorage prefs into
 * it, so an existing user keeps their theme/density/costs. No-op in the browser / preview.
 */
export async function hydrateFromDesktop(): Promise<void> {
  if (!desktop?.getPrefs) return
  try {
    const ui = await desktop.getPrefs()
    if (ui === null) {
      if (desktop.setPrefs) void desktop.setPrefs(uiSnapshot()) // migrate localStorage -> config file
      return
    }
    prefs = {
      ...prefs,
      theme: ui.theme === 'light' || ui.theme === 'system' ? ui.theme : 'dark',
      density: ui.density === 'compact' ? 'compact' : 'comfortable',
      costs: { ...DEFAULT_COSTS, ...ui.costs },
      notifications: { ...DEFAULT_NOTIF, ...ui.notifications },
      pinned: Array.isArray(ui.pinned) ? ui.pinned : prefs.pinned,
      awaitingCollapsed: typeof ui.awaitingCollapsed === 'boolean' ? ui.awaitingCollapsed : prefs.awaitingCollapsed,
    }
    try {
      localStorage.setItem(KEY, JSON.stringify(prefs)) // keep the mirror fresh for next cold start
    } catch {
      /* ignore */
    }
  } catch {
    /* IPC failed — keep the localStorage-loaded prefs already in memory */
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

// Reactive theme read (v3 BUG 3). Theme has several co-mounted writers — the header ThemeToggle,
// the Settings control, and the `t` shortcut — so consumers must NOT cache it in local state (that
// desynced and swallowed the first click after an external change). Subscribing to the store makes
// all consumers agree by construction, in any order. `getThemeMode` is a primitive snapshot, so
// useSyncExternalStore re-renders only when the theme value actually changes.
export function useThemeMode(): ThemeMode {
  return useSyncExternalStore(subscribe, getThemeMode, getThemeMode)
}

// ── Single-writer local-cache caveat (v3 BUG 3) — READ THIS BEFORE ADDING A WRITER ──────────────
// The values below (density, notifications, costs, startup, pinned) are each changed from exactly
// ONE place — the Settings screen, or Live for `pinned` — which also owns the control that reads
// them. So those components legitimately cache the value in local `useState`: with a single writer
// there is nothing to desync from. THEME is the exception (multiple co-mounted writers), which is
// why it is read reactively via `useThemeMode()` above and these are not.
//   ⚠ If you EVER add a second writer for any value below, do NOT keep the local `useState` cache —
//   read it through a `useThemeMode`-style `useSyncExternalStore` hook (the store already notify()s
//   on every change). Leaving the cache in place will reproduce BUG 3 (a stale read → the classic
//   swallowed-first-click / off-by-one toggle).
// ────────────────────────────────────────────────────────────────────────────────────────────────

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

/* ---- "awaiting listing" card collapse (v3 V3-14) — durable so a fold survives restart ---- */
// Single writer (the History AwaitingList toggle owns both read and write), so the component may
// cache it in local `useState` per the single-writer caveat above — no reactive hook needed.
export const getAwaitingCollapsed = (): boolean => prefs.awaitingCollapsed
export function setAwaitingCollapsed(collapsed: boolean): void {
  prefs = { ...prefs, awaitingCollapsed: collapsed }
  save() // durable: localStorage mirror + write-through to the app config file (survives restart)
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
    saveLocal()
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
  saveLocal() // durable startup persistence is the desktop shell's startup:set path, not the ui blob
}

/* ---- native-notification preferences (persisted; read by notifications.ts) ---- */
export const getNotifications = (): NotifPrefs => prefs.notifications
export function setNotifications(notifications: NotifPrefs): void {
  prefs = { ...prefs, notifications }
  save()
}

/* ---- alerts-read (which APPLY signals have been seen; drives the unread badge) ---- */
export const getAlertsSeen = (): string[] => prefs.alertsSeen
export function setAlertsSeen(ids: string[]): void {
  prefs = { ...prefs, alertsSeen: ids }
  saveLocal()
}

/* ---- native notifications (which APPLY crossings have already fired an OS toast) ---- */
export const getNotifiedCrossings = (): string[] => prefs.notifiedCrossings
export function setNotifiedCrossings(keys: string[]): void {
  prefs = { ...prefs, notifiedCrossings: keys }
  saveLocal()
}
export const isNotifSeeded = (): boolean => prefs.notifSeeded
export function markNotifSeeded(): void {
  prefs = { ...prefs, notifSeeded: true }
  saveLocal()
}
