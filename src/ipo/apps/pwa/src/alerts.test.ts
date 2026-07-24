// GATE BUG-2 + F12 — alert retention/notification bounds AND the F12 bell feed, as pure logic run via
// `node --test` (Node's native TS execution — see package.json "test").
//
// Retention (`relevantTransitions`, `pruneRelevantIds`, `pruneSeenIds`) is UNCHANGED — it still keeps
// Open / Closes-Today / Awaiting-listing and drops only Listed, bounding the seen-sets + notifier.
// F12 adds a NARROWER display filter for the bell (`liveApplyCrossings` — book still open), the pure
// `buildAlertFeed` (events/conditions split, dismiss, "!"-replaces-count), and `pruneDismissedKeys`.

import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  buildAlertFeed,
  crossingKey,
  liveApplyCrossings,
  pruneDismissedKeys,
  pruneRelevantIds,
  pruneSeenIds,
  relevantTransitions,
} from './alerts.ts'
import type { IPOListRow, StatusView, VerdictTransition, VerdictType } from './api/types'

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
    listing_overdue: false,
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

// A healthy /status (no degraded condition). Individual tests override records/context_source.
const healthy: StatusView = {
  live_ingest: true,
  last_successful_ingest: '2026-07-14T15:00:00+05:30',
  last_attempt: '2026-07-14T15:00:00+05:30',
  last_attempt_ok: true,
  checked_at: '2026-07-14T15:00:00+05:30',
  records_source: null,
  context_source: null,
  next_refresh_at: null,
}

// The board across a lifecycle: one open, one closing today, one awaiting listing, one already listed.
const board: IPOListRow[] = [
  row('open', { open: -1, close: 2 }),
  row('today', { open: -1, close: 0 }),
  row('await', { open: -5, close: -3 }), // closed, not yet listed
  row('listed', { open: -8, close: -6, listing: -1 }), // outcome resolved → History
]

// Transition log, MOST-RECENT-FIRST (as the engine serves it): two crossings for 'open' (a duplicate),
// a non-crossing change for 'open', crossings for 'today'/'await', a listed IPO, and an off-board ghost.
const OPEN_LATEST = '2026-07-14T15:00:00+05:30'
const log: VerdictTransition[] = [
  xing('open', OPEN_LATEST), // latest 'open' crossing
  xing('open', '2026-07-14T12:00:00+05:30', false), // a later non-crossing change (still relevant)
  xing('today', '2026-07-14T11:00:00+05:30'),
  xing('await', '2026-07-13T15:00:00+05:30'),
  xing('open', '2026-07-10T15:00:00+05:30'), // an OLDER 'open' crossing (the duplicate)
  xing('listed', '2026-07-09T15:00:00+05:30'), // listed → must drop
  xing('ghost', '2026-07-08T15:00:00+05:30'), // not on the board → must drop
]

// ── F4: the bell shows a crossing only while the book is still OPEN ──────────────────────────────
test('liveApplyCrossings keeps only LIVE books — awaiting-listing drops (F4)', () => {
  const ids = liveApplyCrossings(log, board)
    .map((t) => t.ipo_id)
    .sort()
  // 'await' (closed, pre-listing) NO LONGER surfaces — the F4 fix; 'listed' + 'ghost' drop as before.
  assert.deepEqual(ids, ['open', 'today'])
})

test('liveApplyCrossings dedupes to the latest crossing per IPO', () => {
  const openRows = liveApplyCrossings(log, board).filter((t) => t.ipo_id === 'open')
  assert.equal(openRows.length, 1)
  assert.equal(openRows[0].asof, OPEN_LATEST)
})

// ── buildAlertFeed: the events/conditions split, dismiss, and the "!"/count badge ────────────────
test('buildAlertFeed: one list, conditions first then events', () => {
  const ctxAging: StatusView = { ...healthy, records_source: 'vm', context_source: 'local' }
  const feed = buildAlertFeed(log, board, ctxAging, false, new Set(), new Set())
  assert.equal(feed.items[0].kind, 'condition') // conditions on top (persistent signal)
  const conds = feed.items.filter((i) => i.kind === 'condition')
  const events = feed.items.filter((i) => i.kind === 'event')
  assert.equal(conds.length, 1) // context-aging
  assert.deepEqual(
    events.map((e) => (e.kind === 'event' ? e.ipo_id : '')).sort(),
    ['open', 'today'], // F4: await excluded from the feed too
  )
})

test('dismiss removes the matching event but NEVER a condition (f)', () => {
  const ctxAging: StatusView = { ...healthy, records_source: 'vm', context_source: 'local' }
  const feed = buildAlertFeed(log, board, ctxAging, false, new Set([`open@${OPEN_LATEST}`]), new Set())
  const events = feed.items.filter((i) => i.kind === 'event')
  assert.deepEqual(
    events.map((e) => (e.kind === 'event' ? e.ipo_id : '')),
    ['today'], // 'open' dismissed; 'today' remains
  )
  assert.equal(feed.items.filter((i) => i.kind === 'condition').length, 1) // condition untouched
})

test('flag replaces the count when a condition is present; count otherwise (d)', () => {
  // Healthy → no condition → flag null, badge = unread event count (open + today = 2).
  const clean = buildAlertFeed(log, board, healthy, false, new Set(), new Set())
  assert.equal(clean.flag, null)
  assert.equal(clean.badge, 2)
  // Amber condition (context aging) → flag 'amber'.
  const ctxAging: StatusView = { ...healthy, records_source: 'vm', context_source: 'local' }
  assert.equal(buildAlertFeed(log, board, ctxAging, false, new Set(), new Set()).flag, 'amber')
  // Engine unreachable (isError) → the single RED condition → flag 'red'.
  assert.equal(buildAlertFeed(log, board, healthy, true, new Set(), new Set()).flag, 'red')
})

test('badge counts only UNREAD events (seen keys on ipo_id)', () => {
  const feed = buildAlertFeed(log, board, healthy, false, new Set(), new Set(['open']))
  assert.equal(feed.badge, 1) // only 'today' unread
})

test('dismissing every event leaves NO stale count — badge 0 (operator addition 2)', () => {
  const keys = liveApplyCrossings(log, board).map(crossingKey)
  const feed = buildAlertFeed(log, board, healthy, false, new Set(keys), new Set())
  assert.equal(feed.items.filter((i) => i.kind === 'event').length, 0)
  assert.equal(feed.badge, 0) // no stale count even though `seen` never saw those ids
})

// ── the retention/notification bounds — UNCHANGED by F12 ─────────────────────────────────────────
test('relevantTransitions keeps every transition of unresolved IPOs (incl. awaiting-listing)', () => {
  const out = relevantTransitions(log, board)
  // open (×3), today (×1), await (×1) = 5 — retention still keeps awaiting-listing; listed+ghost drop.
  assert.equal(out.length, 5)
  assert.ok(out.every((t) => ['open', 'today', 'await'].includes(t.ipo_id)))
})

test('pruneRelevantIds drops ids that have listed or left the board', () => {
  assert.deepEqual(pruneRelevantIds(['open', 'listed', 'ghost', 'await'], board).sort(), [
    'await',
    'open',
  ])
})

test('pruneSeenIds does NOT wipe the seen-set against a board that has not loaded', () => {
  const seen = ['open', 'await']
  assert.deepEqual(pruneSeenIds(seen, []), seen)
})

test('pruneSeenIds still prunes once the board has actually loaded', () => {
  assert.deepEqual(pruneSeenIds(['open', 'listed', 'ghost', 'await'], board).sort(), [
    'await',
    'open',
  ])
})

// ── F12: the dismissed-crossings prune is bounded AND cold-start-guarded ──────────────────────────
test('pruneDismissedKeys keeps keys for relevant IPOs, drops listed/off-board', () => {
  const keys = ['open@t1', 'listed@t2', 'ghost@t3', 'await@t4']
  // Bounded by RETENTION relevance (not-yet-listed), like pruneSeenIds: 'await' kept, 'listed' dropped.
  assert.deepEqual(pruneDismissedKeys(keys, board).sort(), ['await@t4', 'open@t1'])
})

test('pruneDismissedKeys does NOT wipe the dismissed set against an unloaded board (cold start)', () => {
  const keys = ['open@t1', 'await@t4']
  assert.deepEqual(pruneDismissedKeys(keys, []), keys)
})
