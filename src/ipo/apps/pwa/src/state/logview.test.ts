// V3-16 debug-console view logic (pure) — filtering, repeat-suppression, detail rendering. The
// same functions the ConsoleLog component uses, tested as they ship. Run via `node --test`.

import assert from 'node:assert/strict'
import { test } from 'node:test'
import { collapse, filterEntries, formatDetail, levelClass, levelCode, shortTs } from './logview.ts'

test('levelClass buckets names into info/warn/err and never drops one', () => {
  assert.equal(levelClass('INFO'), 'info')
  assert.equal(levelClass('WARNING'), 'warn')
  assert.equal(levelClass('ERROR'), 'err')
  assert.equal(levelClass('CRITICAL'), 'err')
  assert.equal(levelClass(undefined), 'info') // unknown → neutral, not dropped
  assert.equal(levelCode('warning'), 'WARN')
  assert.equal(levelCode('error'), 'ERR!')
  assert.equal(levelCode('info'), 'INFO')
})

test('formatDetail renders extras as key=val, omitting the columned/internal fields', () => {
  const d = formatDetail({
    ts: 't',
    level: 'INFO',
    message: 'records_from_vm',
    logger: 'x',
    seq: 5,
    ipo_id: 'y',
    count: 8,
  })
  assert.equal(d, 'count=8') // ts/level/message/logger/seq/ipo_id all omitted
  // false is kept (not null); a JWT/token would already be [REDACTED] upstream
  assert.match(formatDetail({ message: 'm', outcome: 'abstained', preserved: false }), /outcome=abstained/)
})

test('filterEntries filters by level chip and by ipo_id/event query', () => {
  const es = [
    { level: 'INFO', message: 'scheduler_cycle_start', ipo_id: '' },
    { level: 'WARN', message: 'overdue_listing_detected', ipo_id: 'vmm' },
    { level: 'ERROR', message: 'scheduler_cycle_failed', ipo_id: '' },
  ]
  assert.deepEqual(
    filterEntries(es, { level: 'warn', query: '' }).map((e) => e.message),
    ['overdue_listing_detected'],
  )
  assert.deepEqual(
    filterEntries(es, { level: 'all', query: 'vmm' }).map((e) => e.message),
    ['overdue_listing_detected'], // matches ipo_id
  )
  assert.deepEqual(
    filterEntries(es, { level: 'all', query: 'cycle' }).map((e) => e.message),
    ['scheduler_cycle_start', 'scheduler_cycle_failed'], // matches event name
  )
  assert.equal(filterEntries(es, { level: 'err', query: 'nope' }).length, 0)
})

test('collapse folds a consecutive run of identical events into one counted row', () => {
  const rows = collapse([
    { level: 'WARN', message: 'fetch_retry', ipo_id: '', seq: 1 },
    { level: 'WARN', message: 'fetch_retry', ipo_id: '', seq: 2 },
    { level: 'WARN', message: 'fetch_retry', ipo_id: '', seq: 3 },
    { level: 'INFO', message: 'live_refresh_done', ipo_id: '', seq: 4 },
    { level: 'WARN', message: 'fetch_retry', ipo_id: '', seq: 5 }, // interrupted → a NEW run
  ])
  assert.equal(rows.length, 3)
  assert.equal(rows[0].count, 3) // ×3 collapsed — one counted line, not three
  assert.equal(rows[0].entry.seq, 3) // latest entry's detail kept
  assert.equal(rows[1].count, 1)
  assert.equal(rows[2].count, 1) // the interrupted run is its own row, never merged across the gap
})

test('collapse keeps different ipo_ids distinct even under the same event', () => {
  const rows = collapse([
    { level: 'WARN', message: 'overdue_listing_detected', ipo_id: 'a' },
    { level: 'WARN', message: 'overdue_listing_detected', ipo_id: 'b' },
  ])
  assert.equal(rows.length, 2)
})

test('shortTs slices HH:MM:SS.mmm out of the ISO timestamp', () => {
  assert.equal(shortTs('2026-07-16T09:42:00.118+05:30'), '09:42:00.118')
  assert.equal(shortTs(undefined), '')
})
