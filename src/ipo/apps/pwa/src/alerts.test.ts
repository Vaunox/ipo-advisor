// GATE BUG-2 — alert retention is relevance-based and bounded (v3). Pure-logic test over a simulated
// multi-IPO cycle, run via `node --test` (Node's native TS execution — see package.json "test").
//
// Asserts the adjusted retention rule: an alert lives while its IPO's outcome is UNRESOLVED — Open /
// Closes-Today / Awaiting-listing all KEEP it; only a Listed IPO drops. Crossings dedupe to the
// latest per IPO; crossings for listed or off-board IPOs are dropped; the persisted seen-set prunes.

import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  currentApplyAlerts,
  pruneRelevantIds,
  relevantApplyCrossings,
  relevantTransitions,
} from './alerts.ts'
import type { IPOListRow, VerdictTransition, VerdictType } from './api/types'

// A local YYYY-MM-DD `offsetDays` from today (status.ts compares against local midnight).
function ymd(offsetDays: number): string {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() + offsetDays)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function row(
  id: string,
  o: { open: number; close: number; listing?: number | null; verdict?: VerdictType },
): IPOListRow {
  return {
    ipo_id: id,
    name: id,
    segment: 'mainboard',
    issue_size_cr: null,
    ofs_fraction: null,
    issue_pe: null,
    peer_median_pe: null,
    open_date: ymd(o.open),
    close_date: ymd(o.close),
    listing_date: o.listing == null ? null : ymd(o.listing),
    verdict: o.verdict ?? 'APPLY',
    probability: 0.9,
    reason: '',
    watch: [],
    kill_flags: [],
  }
}

function xing(ipo: string, asof: string, crossed = true): VerdictTransition {
  return {
    ipo_id: ipo,
    name: ipo,
    asof,
    from_verdict: 'MARGINAL',
    to_verdict: crossed ? 'APPLY' : 'MARGINAL',
    probability: 0.9,
    crossed_into_apply: crossed,
  }
}

// The board across a lifecycle: one open, one closing today, one awaiting listing, one already listed.
const board: IPOListRow[] = [
  row('open', { open: -1, close: 2 }),
  row('today', { open: -1, close: 0 }),
  row('await', { open: -5, close: -3 }), // closed, not yet listed
  row('listed', { open: -8, close: -6, listing: -1 }), // outcome resolved → History
]

// Transition log, MOST-RECENT-FIRST (as the engine serves it). Note: two crossings for 'open'
// (a duplicate), a crossing for the 'listed' IPO, one for a 'ghost' not on the board, and a
// non-crossing verdict change for 'open'.
const log: VerdictTransition[] = [
  xing('open', '2026-07-14T15:00:00+05:30'), // latest 'open' crossing
  xing('open', '2026-07-14T12:00:00+05:30', false), // a later non-crossing change (still relevant)
  xing('today', '2026-07-14T11:00:00+05:30'),
  xing('await', '2026-07-13T15:00:00+05:30'),
  xing('open', '2026-07-10T15:00:00+05:30'), // an OLDER 'open' crossing (the duplicate)
  xing('listed', '2026-07-09T15:00:00+05:30'), // listed → must drop
  xing('ghost', '2026-07-08T15:00:00+05:30'), // not on the board → must drop
]

test('crossings dedupe to the latest per IPO and drop listed / off-board IPOs', () => {
  const out = relevantApplyCrossings(log, board)
  const ids = out.map((t) => t.ipo_id).sort()
  assert.deepEqual(ids, ['await', 'open', 'today']) // awaiting-listing KEPT; listed + ghost dropped
  // 'open' appears exactly once, and it's the LATEST crossing (15:00, not the 10th's).
  const openRows = out.filter((t) => t.ipo_id === 'open')
  assert.equal(openRows.length, 1)
  assert.equal(openRows[0].asof, '2026-07-14T15:00:00+05:30')
})

test('current APPLY signals exclude a listed IPO', () => {
  const ids = currentApplyAlerts(board)
    .map((r) => r.ipo_id)
    .sort()
  assert.deepEqual(ids, ['await', 'open', 'today']) // 'listed' (APPLY but resolved) excluded
})

test('the alert view stays bounded — not the raw log length', () => {
  // 7 rows in the log, but only 3 still-relevant distinct APPLY-crossing IPOs surface.
  assert.equal(relevantApplyCrossings(log, board).length, 3)
})

test('relevantTransitions keeps every transition of unresolved IPOs, drops the rest', () => {
  const out = relevantTransitions(log, board)
  // open (×3: 2 crossings + 1 non-crossing), today (×1), await (×1) = 5; listed + ghost dropped.
  assert.equal(out.length, 5)
  assert.ok(out.every((t) => ['open', 'today', 'await'].includes(t.ipo_id)))
})

test('pruneRelevantIds drops ids that have listed or left the board', () => {
  assert.deepEqual(pruneRelevantIds(['open', 'listed', 'ghost', 'await'], board).sort(), [
    'await',
    'open',
  ])
})

test('awaiting-listing is retained but does not reintroduce unboundedness', () => {
  // The adjusted rule: an awaiting-listing IPO's alert survives (user has applied, outcome pending)…
  assert.ok(relevantApplyCrossings(log, board).some((t) => t.ipo_id === 'await'))
  // …until it lists, at which point it drops. Simulate 'await' listing today:
  const afterListing = board.map((r) =>
    r.ipo_id === 'await' ? { ...r, listing_date: ymd(0) } : r,
  )
  assert.ok(!relevantApplyCrossings(log, afterListing).some((t) => t.ipo_id === 'await'))
})
