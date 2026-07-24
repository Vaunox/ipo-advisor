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
  dismissedCrossings: string[]
  notifSeeded: boolean
  awaitingCollapsed: boolean
  devConsole: boolean
}

// Broker sell-cost display defaults (net-of-cost History column only — never a verdict/probability;
// the engine's label uses config `sell_costs`). `oth` = exchange + SEBI + 18% GST as a % of sell
// value: NSE cash txn 0.00297% + SEBI 0.0001% + GST on those ≈ 0.0036% (verified vs NSE/SEBI Oct-2024
// rates). Was 0.05% — a ~14× overstatement that understated net gains.
const DEFAULT_COSTS: Costs = { stt: 0.1, dp: 15.34, oth: 0.0036 }
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
      dismissedCrossings: Array.isArray(p.dismissedCrossings) ? p.dismissedCrossings : [],
      notifSeeded: p.notifSeeded === true,
      awaitingCollapsed: p.awaitingCollapsed === true,
      devConsole: p.devConsole === true, // v3 V3-16: default OFF — a fresh install ships it off
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
      dismissedCrossings: [],
      notifSeeded: false,
      awaitingCollapsed: false,
      devConsole: false,
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
  devConsole: boolean
}
// OP-3: the notification seen-sets get their OWN durable store (seen-state.json), separate from the
// UiPrefs config file — they advance frequently (notifiedCrossings on every board update), so routing
// them through the low-frequency config file would thrash it. Bounding stays upstream (alerts.ts); this
// only persists what it's handed.
interface SeenState {
  alertsSeen: string[]
  notifiedCrossings: string[]
  dismissedCrossings: string[]
  notifSeeded: boolean
  lastSeen: Record<string, VerdictType>
}
interface DesktopBridge {
  getPrefs?: () => Promise<UiPrefs | null>
  setPrefs?: (ui: UiPrefs) => Promise<void>
  getSeen?: () => Promise<SeenState | null>
  setSeen?: (seen: SeenState) => Promise<void>
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
    devConsole: prefs.devConsole,
  }
}

// OP-3: the seen-sets snapshot written to the SEPARATE seen-state store (never uiSnapshot/settings.json).
function seenSnapshot(): SeenState {
  return {
    alertsSeen: prefs.alertsSeen,
    notifiedCrossings: prefs.notifiedCrossings,
    dismissedCrossings: prefs.dismissedCrossings,
    notifSeeded: prefs.notifSeeded,
    lastSeen: prefs.lastSeen,
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

// OP-3 durable save for the notification seen-sets: the localStorage mirror PLUS a write-through to
// the SEPARATE seen-state store (seen-state.json) — never the config file. Used by the three seen-sets
// (alertsSeen, notifiedCrossings, lastSeen) so they survive a desktop restart without the file://
// localStorage loss, while settings.json stays a low-frequency deliberate-settings store.
function saveSeen() {
  saveLocal()
  // Fire-and-forget — a failed IPC must never break the UI (the localStorage mirror still holds).
  if (desktop?.setSeen) void desktop.setSeen(seenSnapshot())
}

/**
 * Desktop only: hydrate the in-memory prefs from the durable stores before first paint, so a restart
 * shows the saved settings AND the persisted notification seen-sets rather than defaults/empty. Two
 * stores: the UI-prefs config file (settings.json) and the OP-3 seen-state file (seen-state.json).
 * Each uses the first-run null->migrate pattern (config file has no data yet on first upgrade, so we
 * migrate the current localStorage in). No-op in the browser / preview (no bridge).
 */
export async function hydrateFromDesktop(): Promise<void> {
  if (!desktop) return
  await hydrateUiPrefs()
  await hydrateSeenState()
}

// UI prefs (theme/density/costs/notifications/pinned/awaitingCollapsed/devConsole) <- settings.json.
async function hydrateUiPrefs(): Promise<void> {
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
      devConsole: typeof ui.devConsole === 'boolean' ? ui.devConsole : prefs.devConsole,
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

// OP-3: the notification seen-sets <- seen-state.json. Same first-run null->migrate pattern. On a
// restart this reloads the durable seen-sets so the bell doesn't re-fire already-seen crossings and
// the unread/CHANGED badges don't re-light (the file:// localStorage having been lost on the shell).
async function hydrateSeenState(): Promise<void> {
  if (!desktop?.getSeen) return
  try {
    const seen = await desktop.getSeen()
    if (seen === null) {
      if (desktop.setSeen) void desktop.setSeen(seenSnapshot()) // migrate localStorage -> seen-state.json
      return
    }
    prefs = {
      ...prefs,
      alertsSeen: Array.isArray(seen.alertsSeen) ? seen.alertsSeen : prefs.alertsSeen,
      notifiedCrossings: Array.isArray(seen.notifiedCrossings)
        ? seen.notifiedCrossings
        : prefs.notifiedCrossings,
      dismissedCrossings: Array.isArray(seen.dismissedCrossings)
        ? seen.dismissedCrossings
        : prefs.dismissedCrossings,
      notifSeeded: typeof seen.notifSeeded === 'boolean' ? seen.notifSeeded : prefs.notifSeeded,
      lastSeen: seen.lastSeen && typeof seen.lastSeen === 'object' ? seen.lastSeen : prefs.lastSeen,
    }
    try {
      localStorage.setItem(KEY, JSON.stringify(prefs)) // keep the mirror fresh for next cold start
    } catch {
      /* ignore */
    }
  } catch {
    /* IPC failed — keep the localStorage-loaded seen-sets already in memory */
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

/* ---- dev console (v3 V3-16) — durable on/off, default OFF; the ` key toggles it open when ON ---- */
// Read REACTIVELY (like theme, not the single-writer caches above): the Settings toggle writes it,
// but App also reads it and must react to Settings' write — close the console + deaden the ` key
// the instant it's turned off. The console-OPEN state is separate ephemeral React state in App and
// is deliberately NOT persisted (a dev affordance is closed on restart). `getDevConsole` is a
// primitive snapshot, so useSyncExternalStore re-renders only when the flag actually flips.
export const getDevConsole = (): boolean => prefs.devConsole
export function setDevConsole(on: boolean): void {
  prefs = { ...prefs, devConsole: on }
  save() // durable: localStorage mirror + write-through to the app config file (survives restart)
}
export function useDevConsole(): boolean {
  return useSyncExternalStore(subscribe, getDevConsole, getDevConsole)
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

/* ---- last-seen verdicts (CHANGED badge) — review #8 ---- */

// The badge lights when an IPO's VERDICT CATEGORY (never its probability) has moved since the user
// last saw it. Three PURE rules over the lastSeen map, so the logic is node --test'd and can't drift:
//
// * MISSING BASELINE = NOT CHANGED. An IPO with no baseline (never seen, or it left Live and came
//   back) seeds SILENTLY → no badge. This single rule kills both the new-IPO false-light and the
//   leaves-and-returns false-light; the badge lights only on a SUBSEQUENT real move. It is `id in
//   lastSeen`, NOT `undefined !== verdict` (the un-guarded form the review described — see #8).
// * hasChanged: a baseline exists AND the current verdict differs.
// * withSeen: advance one IPO's baseline (on Detail-open).
//
// Each returns the SAME map reference when nothing changed, so `useLastSeen`'s useSyncExternalStore
// re-renders on a real change only — never on a no-op, and never in a loop.

/** Seed a baseline for every incoming IPO that lacks one; leave existing baselines untouched
 *  (per-IPO + incremental — NOT one write-once snapshot). Same ref back if nothing was missing. */
export function seedMissingBaselines(
  prev: Record<string, VerdictType>,
  incoming: Record<string, VerdictType>,
): Record<string, VerdictType> {
  const additions: Record<string, VerdictType> = {}
  let any = false
  for (const [id, verdict] of Object.entries(incoming)) {
    if (!(id in prev)) {
      additions[id] = verdict
      any = true
    }
  }
  return any ? { ...prev, ...additions } : prev
}

/** CHANGED iff a baseline EXISTS and the current verdict differs from it. A missing baseline is
 *  never "changed" — the load-bearing rule that kills the new-IPO / leaves-and-returns false-lights. */
export function hasChanged(
  lastSeen: Record<string, VerdictType>,
  id: string,
  verdict: VerdictType,
): boolean {
  return id in lastSeen && lastSeen[id] !== verdict
}

/** Advance ONE IPO's baseline to `verdict` (marks it seen). Same ref back if already at `verdict`. */
export function withSeen(
  lastSeen: Record<string, VerdictType>,
  id: string,
  verdict: VerdictType,
): Record<string, VerdictType> {
  if (lastSeen[id] === verdict) return lastSeen
  return { ...lastSeen, [id]: verdict }
}

export const getLastSeen = (): Record<string, VerdictType> => prefs.lastSeen

/** Seed baselines for the IPOs on the LIVE board that lack one — silently, no badge. Runs each data
 *  load (kills the old `length === 0` write-once snapshot that froze at first launch). */
export function seedLastSeen(board: Record<string, VerdictType>): void {
  const next = seedMissingBaselines(prefs.lastSeen, board)
  if (next !== prefs.lastSeen) {
    prefs = { ...prefs, lastSeen: next }
    saveSeen() // OP-3: durable seen-state store (survives restart), not localStorage-only
  }
}

/** Mark one IPO seen — advance its baseline to the current verdict (called on Detail-open). */
export function markSeen(id: string, verdict: VerdictType): void {
  const next = withSeen(prefs.lastSeen, id, verdict)
  if (next !== prefs.lastSeen) {
    prefs = { ...prefs, lastSeen: next }
    saveSeen() // OP-3: durable seen-state store (survives restart), not localStorage-only
  }
}

/** Reactive read of the last-seen map (BUG-3 pattern, like `useThemeMode`): Live re-renders when a
 *  baseline advances, so the CHANGED badge actually drops on Detail-open — never a stale cached read.
 *  lastSeen accretes one small verdict-enum entry per IPO; left UNPRUNED on purpose (bounded and tiny,
 *  and pruning would only reintroduce a reseed-on-return we want silent anyway). OP-3 will upgrade the
 *  durability of all these seen-sets later; #8 rides on it for free. */
export function useLastSeen(): Record<string, VerdictType> {
  return useSyncExternalStore(subscribe, getLastSeen, getLastSeen)
}

/* ---- broker cost assumptions ---- */
export const getCosts = (): Costs => prefs.costs
export function setCosts(costs: Costs): void {
  prefs = { ...prefs, costs }
  save()
}

// F5: an absurdity ceiling for a committed cost. Its only job is to reject runaway/typo values; real
// broker costs (STT ~0.1%, DP ~₹15, exchange+GST+SEBI ~0.05%) are orders of magnitude below it. One
// generous guard, not a per-field bound.
export const COST_MAX = 100_000

// F5: commit a broker-cost field from its raw draft string — the PURE seam behind the Settings
// inputs (node-tested, so the entry logic can't drift). ONE rule, no special cases: return the parsed
// value ONLY if it is a valid, finite, non-negative decimal within `max`; otherwise return `fallback`
// UNCHANGED. So a valid entry commits and everything invalid REVERTS — "" (empty), a lone ".", a
// sign ("-5"), non-numeric ("5abc"), non-finite, or above-max — and nothing is ever silently
// substituted (the old `parseFloat(v) || 0` committed 0 for all of those, so a cleared field became a
// wrong 0% cost). `Number` (not `parseFloat`) is deliberate: it rejects trailing garbage
// ("5abc" → NaN → revert) that `parseFloat` would accept as 5. An explicit "0" is a valid, deliberate
// choice and commits 0; an empty field reverts. The shape gate accepts "5." (→5) and ".5" (→0.5) so a
// mid-typed decimal that reaches blur still commits its numeric value.
export function commitCost(raw: string, fallback: number, max = COST_MAX): number {
  const s = raw.trim()
  if (!/^\d+\.?\d*$|^\.\d+$/.test(s)) return fallback // digits + at most one dot; no sign/exp/garbage
  const n = Number(s)
  if (!Number.isFinite(n) || n > max) return fallback
  return n
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
  saveSeen() // OP-3: durable seen-state store (survives restart), not localStorage-only
}

/* ---- native notifications (which APPLY crossings have already fired an OS toast) ---- */
export const getNotifiedCrossings = (): string[] => prefs.notifiedCrossings
export function setNotifiedCrossings(keys: string[]): void {
  prefs = { ...prefs, notifiedCrossings: keys }
  saveSeen() // OP-3: durable seen-state store (survives restart), not localStorage-only
}

/* ---- dismissed crossings (F12) — which APPLY crossings the user has cleared from the bell ---- */
// A SEPARATE set from notifiedCrossings (which the native notifier auto-advances every cycle; reusing
// it would make dismissals evaporate). Keyed per-crossing `ipo_id@asof` (alerts.ts `crossingKey`),
// bounded by pruneDismissedKeys. Durable via the OP-3 seen-state store so a dismissal survives restart.
export const getDismissedCrossings = (): string[] => prefs.dismissedCrossings
export function setDismissedCrossings(keys: string[]): void {
  prefs = { ...prefs, dismissedCrossings: keys }
  saveSeen() // OP-3: durable seen-state store (survives restart), not localStorage-only
}
export const isNotifSeeded = (): boolean => prefs.notifSeeded
export function markNotifSeeded(): void {
  prefs = { ...prefs, notifSeeded: true }
  saveSeen() // OP-3: durable seen-state store (survives restart), not localStorage-only
}
