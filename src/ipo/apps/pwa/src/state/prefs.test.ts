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
import type { VerdictType } from '../api/types'

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

// --- CHANGED badge (review #8): the pure seed / changed / seen rules ------------------------------

const A: VerdictType = 'APPLY'
const S: VerdictType = 'SKIP'

test('a new IPO seeds a baseline silently — NOT changed (the mis-fire this kills)', () => {
  const seeded = P.seedMissingBaselines({}, { x: A }) // x first appears on Live
  assert.deepEqual(seeded, { x: A })
  assert.equal(P.hasChanged(seeded, 'x', A), false) // just seeded → no badge
})

test('a missing baseline is never "changed" (no undefined !== verdict false-light)', () => {
  assert.equal(P.hasChanged({}, 'x', A), false)
})

test('a verdict move lights CHANGED; opening Detail advances the baseline and clears it', () => {
  const seeded = P.seedMissingBaselines({}, { x: A })
  assert.equal(P.hasChanged(seeded, 'x', S), true) // A -> S is a real move
  const advanced = P.withSeen(seeded, 'x', S) // Detail-open marks it seen at S
  assert.equal(P.hasChanged(advanced, 'x', S), false) // cleared
  assert.equal(P.hasChanged(advanced, 'x', A), true) // a SUBSEQUENT move (S -> A) re-fires
})

test('per-IPO + incremental: a second IPO appearing does not reset the first', () => {
  const one = P.seedMissingBaselines({}, { x: A }) // x seeded at A
  const two = P.seedMissingBaselines(one, { x: S, y: S }) // y appears; x already has a baseline
  assert.equal(two.x, A) // x's baseline is UNTOUCHED (not reseeded to S)
  assert.equal(two.y, S) // y seeded silently
  assert.equal(P.hasChanged(two, 'x', S), true) // x's real move A->S still detected against A
})

test('leaves-and-returns: an IPO that left Live and returns unchanged does NOT false-light', () => {
  const seeded = P.seedMissingBaselines({}, { x: A }) // x on Live at A
  const away = P.seedMissingBaselines(seeded, { y: S }) // x leaves; seeding only ADDS, baseline stays
  assert.equal(away.x, A) // baseline persisted (unpruned)
  assert.equal(P.hasChanged(away, 'x', A), false) // returns unchanged → no badge (no false-light)
  assert.equal(P.hasChanged(away, 'x', S), true) // a genuine move while away still lights
})

test('not frozen to install: seeding is incremental, so a later change is still detected', () => {
  const seeded = P.seedMissingBaselines({ x: A }, { x: A }) // baseline set earlier; no-op here
  assert.equal(P.hasChanged(seeded, 'x', S), true) // a change after the snapshot IS detected
})

test('ref-stability: seed/withSeen return the SAME map when nothing changed (no needless re-render)', () => {
  const prev = { x: A }
  assert.equal(P.seedMissingBaselines(prev, { x: S }), prev) // x present → no reseed → same ref
  assert.equal(P.withSeen(prev, 'x', A), prev) // already A → same ref
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

test('devConsole is OFF by default and setDevConsole persists + notifies (v3 V3-16)', () => {
  assert.equal(P.getDevConsole(), false) // a fresh install ships the console OFF
  let hits = 0
  const unsub = P.subscribe(() => {
    hits++
  })
  P.setDevConsole(true)
  assert.equal(P.getDevConsole(), true) // read through the store (backs useDevConsole) — no cache
  assert.ok(hits >= 1, 'a write notifies subscribers, so App reacts when Settings flips it')
  P.setDevConsole(false)
  assert.equal(P.getDevConsole(), false)
  unsub()
})

// --- F5: broker-cost input commit — the pure seam behind the Settings decimal inputs -------------
// The bug: inputs were bound to the PARSED NUMBER with `parseFloat(v) || 0` per keystroke, so "0."
// collapsed to 0 (decimal unenterable) and a cleared field committed a wrong 0% cost. commitCost is
// the ONE rule the fix rests on: a valid decimal commits, everything else reverts to the fallback.

test('commitCost: a valid decimal commits verbatim (0.05 was the unenterable case)', () => {
  assert.equal(P.commitCost('0.05', 0.1), 0.05)
  assert.equal(P.commitCost('5.5', 0.1), 5.5)
  assert.equal(P.commitCost('15.34', 15.34), 15.34) // the DP default round-trips
  assert.equal(P.commitCost('.5', 0.1), 0.5) // leading-dot decimal
  assert.equal(P.commitCost('5.', 0.1), 5) // a mid-typed trailing dot commits its number
  assert.equal(P.commitCost('007', 0.1), 7) // leading zeros normalize
})

test('commitCost: explicit "0" commits 0 (a real choice), but an empty field REVERTS', () => {
  assert.equal(P.commitCost('0', 0.1), 0) // a deliberate zero commits — the design distinction
  assert.equal(P.commitCost('', 0.1), 0.1) // empty → fallback, NEVER a silent 0 (the `|| 0` bug)
})

test('commitCost: every invalid draft reverts to fallback — one rule, no silent substitution', () => {
  const fb = 0.1
  assert.equal(P.commitCost('.', fb), fb) // a lone dot
  assert.equal(P.commitCost('-5', fb), fb) // negative REVERTS (not clamped to 0 — a value never typed)
  assert.equal(P.commitCost('abc', fb), fb) // non-numeric
  assert.equal(P.commitCost('5abc', fb), fb) // trailing garbage (Number, not parseFloat, rejects it)
  assert.equal(P.commitCost('1e5', fb), fb) // exponent form rejected
  assert.equal(P.commitCost('   ', fb), fb) // whitespace trims to empty → fallback
  assert.equal(P.commitCost('Infinity', fb), fb) // non-finite
})

test('commitCost: the value AT the ceiling commits; just above it reverts', () => {
  assert.equal(P.commitCost(String(P.COST_MAX), 0.1), P.COST_MAX)
  assert.equal(P.commitCost(String(P.COST_MAX + 1), 0.1), 0.1) // above the absurdity guard → revert
})

test('costs round-trip through save() — persist + reload (previously uncovered)', () => {
  const c = { stt: 0.05, dp: 15.34, oth: 0.075 }
  P.setCosts(c)
  assert.deepEqual(P.getCosts(), c) // in-memory store holds the committed numbers
  const raw = (
    globalThis as unknown as { localStorage: { getItem(k: string): string | null } }
  ).localStorage.getItem('ipoadv')
  assert.ok(raw, 'setCosts → save() persisted prefs to the localStorage mirror')
  assert.deepEqual(JSON.parse(raw as string).costs, c) // survives a reload (round-trip)
})
