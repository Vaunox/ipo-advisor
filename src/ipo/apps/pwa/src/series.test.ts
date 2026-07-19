// v3-DP DP-3b — the "UI must never lie" cases for the subscription-history chart.
//
// Pure-logic tests over the ONE shared module (series.ts), run via `node --test`, so the rules that
// decide what the user is told are the rules under test — the same discipline as status.test.ts.
//
// The load-bearing assertion in this file is that `not_recorded` and `unavailable` stay distinct in
// the WORDS a user reads, not merely in a state value they never see. An empty chart captioned
// "nothing was recorded" when the truth is "we couldn't reach the server" is the UI stating an
// absence it cannot vouch for.

import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { SeriesSample, SeriesView } from './api/types'
import { MESSAGES, chartState, fmtMultiple, freshnessLabel, splitRuns } from './series.ts'

const T0 = Date.parse('2026-05-15T10:00:00+05:30')
const CYCLE = 30 * 60 * 1000

function sample(offsetCycles: number, qib = 1): SeriesSample {
  return {
    schema_version: 1,
    captured_at: new Date(T0 + offsetCycles * CYCLE).toISOString(),
    source_update_time: 'Updated as on 15-May-2026 10:00:00',
    qib_sub: qib,
    nii_sub: qib * 0.6,
    snii_sub: qib * 0.8,
    bnii_sub: qib * 0.5,
    retail_sub: qib * 0.4,
    total_sub: qib * 0.7,
  }
}

function view(state: SeriesView['state'], samples: SeriesSample[] = []): SeriesView {
  return {
    ipo_id: 'x',
    available: state === 'recorded' || state === 'not_recorded',
    state,
    refreshed_at: samples.length ? samples[samples.length - 1].captured_at : null,
    samples,
  }
}

// --- the four states stay distinct ---------------------------------------------------------------

test('an empty series reads as NOT RECORDED, not as a broken chart', () => {
  const s = chartState(view('not_recorded'), false)
  assert.equal(s, 'not_recorded')
  const copy = MESSAGES.not_recorded
  assert.match(copy.title, /no subscription history recorded/i)
  assert.ok(!copy.warn, 'honest absence must not wear the amber "something went wrong" treatment')
})

test('UNAVAILABLE is worded distinctly from NOT RECORDED — the load-bearing case', () => {
  const nr = MESSAGES.not_recorded
  const un = MESSAGES.unavailable

  assert.notEqual(nr.title, un.title)
  assert.notEqual(nr.detail, un.detail)
  assert.ok(un.warn, 'unavailable is "we could not find out" — it earns the amber treatment')
  assert.ok(!nr.warn, 'honest absence is not a fault and must not wear the fault treatment')

  // The two must talk about DIFFERENT SUBJECTS, which is what keeps them from being read as the
  // same thing. `unavailable` names a connection failure; `not_recorded` names this IPO's own
  // history. We deliberately do NOT spell out "this doesn't mean nothing was recorded" — that
  // explains our bookkeeping to someone who never had the wrong idea.
  assert.match(`${un.title} ${un.detail}`, /couldn't reach|server/i)
  assert.match(`${nr.title} ${nr.detail}`, /recorded|recording/i)

  // The critical negative: the unavailable copy must never ASSERT an absence it cannot vouch for.
  assert.ok(
    !/no subscription history|nothing was recorded|never recorded/i.test(`${un.title} ${un.detail}`),
    'unavailable must not claim the series is empty — we do not know that',
  )
})

test('LOADING is its own state, never the empty frame', () => {
  assert.equal(chartState(undefined, true), 'loading')
  assert.equal(chartState(view('not_recorded'), true), 'loading', 'loading wins while in flight')
  assert.notEqual(MESSAGES.loading.title, MESSAGES.not_recorded.title)
})

test('a failed fetch is UNAVAILABLE, never "nothing recorded"', () => {
  assert.equal(chartState(undefined, false), 'unavailable')
})

test('every non-plotting state has its own headline — none collapse', () => {
  const titles = Object.values(MESSAGES).map((m) => m.title)
  assert.equal(new Set(titles).size, titles.length, `copy collapsed: ${titles.join(' | ')}`)
})

test('on-screen copy carries no internal vocabulary', () => {
  // A retail reader does not know what a "data plane" or a "trajectory" is, and "in this build" is
  // developer-speak. The wire STATE values keep those precise names; the sentences must not.
  const banned = /data plane|trajectory|in this build|envelope|VM\b/i
  for (const [state, copy] of Object.entries(MESSAGES)) {
    assert.ok(!banned.test(copy.title), `${state} title leaks internal wording: ${copy.title}`)
    assert.ok(!banned.test(copy.detail ?? ''), `${state} detail leaks internal wording: ${copy.detail}`)
  }
})

test('the wire state VALUES are unchanged — the DP-3a contract and log fields', () => {
  // Deliberately asserted: the copy rewrite must never drift the values the engine logs and tests
  // assert on. `state=unavailable` in a log line is exactly the precision an operator wants.
  assert.deepEqual(Object.keys(MESSAGES).sort(), ['loading', 'not_loaded', 'not_recorded', 'unavailable'])
  assert.equal(chartState(view('recorded', [sample(0)]), false), 'recorded')
  assert.equal(chartState(view('not_loaded'), false), 'not_loaded')
})

// --- the gap must never be bridged ---------------------------------------------------------------

test('a fetch gap SPLITS the line — absence of geometry, not an interpolated bridge', () => {
  // Cycles 0,1,2 then a hole, then 8,9,10 — DP-1 banked nothing across the hole.
  const samples = [0, 1, 2, 8, 9, 10].map((i) => sample(i))
  const runs = splitRuns(samples)

  assert.equal(runs.length, 2, 'the gap must break the series into two runs')
  assert.equal(runs[0].length, 3)
  assert.equal(runs[1].length, 3)
  // No run may span the hole — that would be the chart inventing readings the recorder refused to
  // fabricate.
  for (const run of runs) {
    const ts = run.map((s) => Date.parse(s.captured_at))
    const maxStep = Math.max(...ts.slice(1).map((t, i) => t - ts[i]))
    assert.ok(maxStep <= CYCLE * 1.8, 'a run bridged the gap')
  }
})

test('an unbroken series stays ONE run', () => {
  assert.equal(splitRuns([0, 1, 2, 3, 4].map((i) => sample(i))).length, 1)
})

test('a FLAT book is one run of unchanging values — recorded, not missing', () => {
  // The real cmll case: a weekend, no bidding, identical readings. This is signal, and it must
  // render as a flat line rather than being mistaken for a gap.
  const flat = [0, 1, 2, 3].map((i) => sample(i, 0.2933439937823973))
  const runs = splitRuns(flat)
  assert.equal(runs.length, 1, 'unchanging values must not be treated as a gap')
  assert.equal(new Set(runs[0].map((s) => s.qib_sub)).size, 1, 'the values really are identical')
})

test('splitRuns handles the degenerate sizes without inventing runs', () => {
  assert.deepEqual(splitRuns([]), [])
  assert.equal(splitRuns([sample(0)]).length, 1)
})

// --- freshness is per-IPO, and grammatical -------------------------------------------------------

test('freshness reads updating while open and complete once closed', () => {
  const v = view('recorded', [sample(0), sample(1)])
  assert.match(freshnessLabel(v, false), /^updating/)
  assert.match(freshnessLabel(v, true), /^complete/)
})

test('the reading count is singular for one and plural otherwise', () => {
  assert.match(freshnessLabel(view('recorded', [sample(0)]), false), /1 reading$/)
  assert.match(freshnessLabel(view('recorded', [sample(0), sample(1)]), false), /2 readings$/)
  assert.match(freshnessLabel(view('recorded', []), true), /0 readings$/)
})

// --- formatting ----------------------------------------------------------------------------------

test('multiples format readably at both ends of the range', () => {
  assert.equal(fmtMultiple(0.2933439937823973), '0.29x')
  assert.equal(fmtMultiple(1.5926609711721422), '1.59x')
  assert.equal(fmtMultiple(92.4), '92x')
})
