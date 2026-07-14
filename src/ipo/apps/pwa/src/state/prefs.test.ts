// GATE BUG-3 — theme is one reactive source of truth (v3). The bug was stale read-side caches: the
// header toggle and Settings each held a private copy of the theme that didn't update when another
// writer changed it, so the first toggle click after a Settings change was swallowed (off-by-one).
//
// The fix makes prefs.ts a subscribable store; consumers read via useSyncExternalStore(subscribe,
// getThemeMode) instead of caching. This test exercises the store core that the hook is built on:
// setThemeMode is the single source, every write notifies subscribers, and a re-read is never stale
// — the invariant that makes all consumers agree in any order. Run via `node --test`.
//
// prefs.ts touches localStorage / window / document at module load, so we shim them, then dynamic-
// import prefs AFTER the shims are in place.

import assert from 'node:assert/strict'
import { test } from 'node:test'

function installShims(): void {
  const store = new Map<string, string>()
  const g = globalThis as unknown as Record<string, unknown>
  g.localStorage = {
    getItem: (k: string) => (store.has(k) ? store.get(k) : null),
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
  }
  g.window = {
    matchMedia: () => ({ matches: false }), // system → light in this env
    setTimeout: () => 0, // applyTheme's animation cleanup — no-op is fine (classList is shimmed)
  }
  g.document = {
    documentElement: { setAttribute() {}, classList: { add() {}, remove() {} } },
  }
}

installShims()
const P = await import('./prefs.ts')

test('setThemeMode is the single source and a re-read is never stale', () => {
  P.setThemeMode('light')
  assert.equal(P.getThemeMode(), 'light')
  P.setThemeMode('dark')
  // Two independent reads (standing in for two consumers) both see the latest — no private cache.
  assert.equal(P.getThemeMode(), 'dark')
  assert.equal(P.getThemeMode(), 'dark')
})

test('every write notifies subscribers (what makes useSyncExternalStore consumers re-read)', () => {
  let hits = 0
  const unsub = P.subscribe(() => {
    hits++
  })
  P.setThemeMode('light')
  P.setThemeMode('dark')
  assert.ok(hits >= 2, `expected >=2 notifications, got ${hits}`)
  // Unsubscribe actually detaches.
  const frozen = hits
  unsub()
  P.setThemeMode('system')
  assert.equal(hits, frozen)
})

test('a change from ANY writer is visible to a reader that reads through the store', () => {
  // Simulate the reported sequence: Settings sets a mode, then the toggle reads it. The toggle
  // computes its next state from resolveTheme(getThemeMode()) — the live store — not a cached copy,
  // so it is never off-by-one.
  P.setThemeMode('light') // "Settings → Light"
  const toggleSees = P.resolveTheme(P.getThemeMode()) // what the toggle would render/act on
  assert.equal(toggleSees, 'light') // not stale 'dark' → the first click would NOT be swallowed
  const nextClick = toggleSees === 'light' ? 'dark' : 'light'
  P.setThemeMode(nextClick)
  assert.equal(P.getThemeMode(), 'dark') // the toggle click actually flips it
})

test('resolveTheme maps system via matchMedia (light in this env)', () => {
  assert.equal(P.resolveTheme('system'), 'light')
  assert.equal(P.resolveTheme('dark'), 'dark')
  assert.equal(P.resolveTheme('light'), 'light')
})
