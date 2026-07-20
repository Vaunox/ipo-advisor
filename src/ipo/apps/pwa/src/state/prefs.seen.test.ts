// GATE OP-3 — the notification seen-sets get a durable home. They were localStorage-only, which the
// desktop shell's file:// origin does not persist across restart → the bell re-fired already-seen
// crossings and the badge re-lit. The fix routes them through a SEPARATE durable store (seen-state.json
// via the desktop bridge's getSeen/setSeen), never the low-frequency config file.
//
// This file runs with the desktop bridge SHIMMED, so `desktop` in prefs.ts resolves to our spies.
// node --test isolates each test FILE in its own process, so prefs.test.ts (which shims NO bridge, i.e.
// browser/dev mode) is unaffected by this file's bridge. Run via `node --test`.

import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { VerdictType } from '../api/types'

interface SeenState {
  alertsSeen: string[]
  notifiedCrossings: string[]
  notifSeeded: boolean
  lastSeen: Record<string, VerdictType>
}

const setSeenCalls: SeenState[] = []
const setPrefsCalls: unknown[] = []
let getSeenReturn: SeenState | null = null

function installShims(): void {
  const store = new Map<string, string>()
  const g = globalThis as unknown as Record<string, unknown>
  g.localStorage = {
    getItem: (k: string) => (store.has(k) ? store.get(k) : null),
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
  }
  g.window = {
    matchMedia: () => ({ matches: false }),
    setTimeout: () => 0,
    // The desktop bridge (preload's window.ipoDesktop). getPrefs null just no-ops the ui-prefs path;
    // getSeen/setSeen are the OP-3 seen-state durable store this file exercises.
    ipoDesktop: {
      getPrefs: async () => null,
      setPrefs: async (ui: unknown) => void setPrefsCalls.push(ui),
      getSeen: async (): Promise<SeenState | null> => getSeenReturn,
      setSeen: async (seen: SeenState) => void setSeenCalls.push(seen),
    },
  }
  g.document = {
    documentElement: { setAttribute() {}, classList: { add() {}, remove() {} } },
  }
}

installShims()
const P = await import('./prefs.ts')

const A: VerdictType = 'APPLY'

test('a seen-set write goes to the durable seen store (setSeen), NOT the config store (setPrefs)', () => {
  const prefsBefore = setPrefsCalls.length
  const seenBefore = setSeenCalls.length
  P.setNotifiedCrossings(['ipo-a@t1'])
  assert.ok(setSeenCalls.length > seenBefore) // routed to the seen store
  assert.ok(setSeenCalls.at(-1)?.notifiedCrossings.includes('ipo-a@t1'))
  assert.equal(setPrefsCalls.length, prefsBefore) // the high-frequency write did NOT touch the config file
})

test('pruning preserved: the persist layer stores the bounded list it is handed, unchanged', () => {
  // Bounding happens upstream (alerts.ts); prefs must persist exactly what it's given, no growth.
  P.setAlertsSeen(['a', 'b'])
  assert.deepEqual(setSeenCalls.at(-1)?.alertsSeen, ['a', 'b'])
})

test('seen-sets survive a restart: hydrateFromDesktop loads the persisted durable state', async () => {
  getSeenReturn = {
    alertsSeen: ['ipo-x'],
    notifiedCrossings: ['ipo-x@t'],
    notifSeeded: true,
    lastSeen: { 'ipo-x': A },
  }
  await P.hydrateFromDesktop()
  assert.deepEqual(P.getAlertsSeen(), ['ipo-x']) // not empty — the bell won't re-fire ipo-x
  assert.deepEqual(P.getNotifiedCrossings(), ['ipo-x@t'])
  assert.equal(P.isNotifSeeded(), true)
  assert.deepEqual(P.getLastSeen(), { 'ipo-x': A }) // #8 CHANGED-badge state rides for free
})

test('first run (getSeen null) migrates the current localStorage seen-sets into the durable store', async () => {
  getSeenReturn = null
  P.setAlertsSeen(['seed-me']) // the in-session state to migrate
  const before = setSeenCalls.length
  await P.hydrateFromDesktop()
  // null -> setSeen(seenSnapshot): the current seen-sets get written to seen-state.json.
  assert.ok(setSeenCalls.length > before)
  assert.ok(setSeenCalls.at(-1)?.alertsSeen.includes('seed-me'))
})
