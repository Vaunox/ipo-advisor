// GATE code-review #9 — the render error boundary's decision logic. Before this, main.tsx mounted the
// app with no boundary: any uncaught render throw unmounted the whole tree (blank white screen). The
// fix adds a boundary; ErrorBoundary.tsx is the (JSX) React glue, and the substantive logic lives in
// the pure boundary.ts so it's testable here under `node --test` (which strips types but not JSX, so a
// .tsx can't be imported — hence the seam). Run via `node --test`.
//
// PROOF SCOPE — stated honestly: this exercises the boundary's OWN logic — derive the fallback state,
// key it for auto-reset on navigation, and format the catch log. It does NOT exercise "React invokes
// getDerivedStateFromError when a child throws" — that is React's own guarantee, and driving it needs
// a client renderer this repo intentionally has none of. A probe confirmed React 18's synchronous
// renderToStaticMarkup does NOT invoke error boundaries (it re-throws the child error), so there is no
// no-new-dependency render-level test to add; adding jsdom/RTL to fake one was declined.

import assert from 'node:assert/strict'
import { test } from 'node:test'
import { contentBoundaryKey, deriveErrorState, formatBoundaryLog } from './boundary.ts'

// --- deriveErrorState: the catch -> fallback transition (what getDerivedStateFromError returns) -----

test('deriveErrorState carries a thrown Error through unchanged', () => {
  const err = new Error('bad shape from engine')
  const state = deriveErrorState(err)
  assert.equal(state.error, err) // same instance — the fallback shows its .message, the log gets it
})

test('deriveErrorState normalizes a non-Error throw so the fallback always has a .message', () => {
  const fromString = deriveErrorState('boom') // React permits throwing a bare string
  assert.ok(fromString.error instanceof Error)
  assert.equal(fromString.error?.message, 'boom')
  const fromNull = deriveErrorState(null)
  assert.ok(fromNull.error instanceof Error)
  assert.equal(fromNull.error?.message, 'null') // honest one-liner, never a crash-on-crash
})

// --- contentBoundaryKey: navigation auto-resets the boundary (a changed key remounts it) ------------

test('a view change changes the key — navigating away from a crashed screen resets the boundary', () => {
  assert.notEqual(contentBoundaryKey('live', null), contentBoundaryKey('history', null))
})

test('the key is stable within one route — no needless remount while you stay put', () => {
  assert.equal(contentBoundaryKey('live', null), contentBoundaryKey('live', null))
})

test('opening a Detail changes the key off the list view (and is independent of the view under it)', () => {
  assert.notEqual(contentBoundaryKey('live', null), contentBoundaryKey('live', 'ipo-42'))
  // detailId dominates: the same open Detail keys the same regardless of which view it was opened from
  assert.equal(contentBoundaryKey('live', 'ipo-42'), contentBoundaryKey('history', 'ipo-42'))
})

test('switching between two Details, and closing one, each change the key (each resets)', () => {
  assert.notEqual(contentBoundaryKey('live', 'ipo-42'), contentBoundaryKey('live', 'ipo-99'))
  assert.notEqual(contentBoundaryKey('live', 'ipo-42'), contentBoundaryKey('live', null)) // back
})

// --- formatBoundaryLog: the renderer-process console.error args on catch ----------------------------

test('formatBoundaryLog returns the tag, the raw error, and the component stack', () => {
  const err = new Error('x')
  assert.deepEqual(formatBoundaryLog(err, 'at Live\n  at App'), [
    '[render] boundary caught',
    err,
    'at Live\n  at App',
  ])
})

test('a missing component stack degrades to an honest placeholder, never undefined', () => {
  assert.equal(formatBoundaryLog(new Error('x'), null)[2], '(no component stack)')
  assert.equal(formatBoundaryLog(new Error('x'), undefined)[2], '(no component stack)')
})

test('spread into console.error, it delivers exactly those args (the componentDidCatch call)', () => {
  const calls: unknown[][] = []
  const orig = console.error
  console.error = (...args: unknown[]) => void calls.push(args)
  try {
    const err = new Error('bad field')
    console.error(...formatBoundaryLog(err, 'at Detail')) // what componentDidCatch does
    assert.equal(calls.length, 1)
    assert.equal(calls[0][0], '[render] boundary caught')
    assert.equal(calls[0][1], err) // the raw error, for devtools inspection
    assert.equal(calls[0][2], 'at Detail')
  } finally {
    console.error = orig
  }
})
