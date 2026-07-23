// V3-16 debug-console view logic (pure) — filtering, repeat-suppression, detail rendering. The
// same functions the ConsoleLog component uses, tested as they ship. Run via `node --test`.

import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  appendCapped,
  collapse,
  filterEntries,
  formatDetail,
  levelClass,
  levelCode,
  levelParam,
  prependOlder,
  resetForLevel,
  shortTs,
  shouldResetCursor,
} from './logview.ts'

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

test('formatDetail keeps a multi-line exc_info traceback intact (F7 clamp is visual-only, data stays whole)', () => {
  // The console clamps long detail to 4 lines with CSS and expands on click — but the DATA must never
  // be truncated (the operator copies the full traceback). exc_info carries embedded newlines.
  const tb =
    'Traceback (most recent call last):\n' +
    '  File "runner.py", line 216, in _run_cycle_guarded\n' +
    '    return service.run_cycle()\n' +
    'httpx.ConnectError: [Errno 111] Connection refused'
  const d = formatDetail({
    ts: 't', level: 'ERROR', logger: 'r', message: 'scheduler_cycle_failed', error: 'boom', exc_info: tb,
  })
  assert.ok(d.includes(tb)) // the whole traceback, every newline, survives formatDetail
  assert.ok(d.includes('error=boom'))
})

test('filterEntries is MIN-level (warn keeps err) + the ipo_id/event query (F8b)', () => {
  const es = [
    { level: 'INFO', message: 'scheduler_cycle_start', ipo_id: '' },
    { level: 'WARN', message: 'overdue_listing_detected', ipo_id: 'vmm' },
    { level: 'ERROR', message: 'scheduler_cycle_failed', ipo_id: '' },
  ]
  assert.deepEqual(
    filterEntries(es, { level: 'warn', query: '' }).map((e) => e.message),
    ['overdue_listing_detected', 'scheduler_cycle_failed'], // MIN-level: warn AND err (never hides errors)
  )
  assert.deepEqual(
    filterEntries(es, { level: 'err', query: '' }).map((e) => e.message),
    ['scheduler_cycle_failed'], // err only (nothing above it)
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

test('prependOlder stitches the ring->disk seam with no duplicate and no gap', () => {
  // current buffer starts at 10:00 (its oldest is also on disk — the boundary overlaps because the
  // `before` cursor is inclusive). Older disk page: 08:00, 09:00, and the 10:00 twin.
  const current = [
    { ts: '2026-07-16T10:00:00+05:30', logger: 'x', message: 'b', ipo_id: '' },
    { ts: '2026-07-16T10:05:00+05:30', logger: 'x', message: 'c', ipo_id: '' },
  ]
  const older = [
    { ts: '2026-07-16T08:00:00+05:30', logger: 'x', message: 'z', ipo_id: '' },
    { ts: '2026-07-16T09:00:00+05:30', logger: 'x', message: 'a', ipo_id: '' },
    { ts: '2026-07-16T10:00:00+05:30', logger: 'x', message: 'b', ipo_id: '' }, // the boundary twin
  ]
  const merged = prependOlder(older, current)
  assert.deepEqual(
    merged.map((e) => e.message),
    ['z', 'a', 'b', 'c'], // z,a prepended; the duplicate 'b' at the seam dropped; nothing lost
  )
  // one 'b' only — no double-line at the boundary
  assert.equal(merged.filter((e) => e.message === 'b').length, 1)
  // fully-overlapping page (nothing older) → same ref, so the caller knows history is exhausted
  assert.equal(prependOlder([older[2]], current), current)
})

test('appendCapped appends new tail lines and keeps only the newest max', () => {
  const prev = [{ message: 'a' }, { message: 'b' }]
  assert.equal(appendCapped(prev, [], 10), prev) // empty poll → same buffer, no churn
  assert.deepEqual(
    appendCapped(prev, [{ message: 'c' }], 10).map((e) => e.message),
    ['a', 'b', 'c'], // appended in order
  )
  assert.deepEqual(
    appendCapped(prev, [{ message: 'c' }, { message: 'd' }], 3).map((e) => e.message),
    ['b', 'c', 'd'], // capped to newest 3 (oldest dropped) — constant memory
  )
})

test('shouldResetCursor fires only on a ring seq regression (engine restart), and cannot loop (F8a)', () => {
  // steady state — the ring only grows within a process, so last_seq >= since -> never a reset
  assert.equal(shouldResetCursor(2205, 2203), false) // new lines arrived this poll
  assert.equal(shouldResetCursor(2203, 2203), false) // no new lines this poll
  // RESTART — a fresh process reset seq to ~1 while the client still polls the old high cursor
  assert.equal(shouldResetCursor(2, 2203), true)
  // first poll / cold start — since=0, empty OR non-empty ring, never a reset (0 < 0 is false)
  assert.equal(shouldResetCursor(0, 0), false)
  assert.equal(shouldResetCursor(5, 0), false)
  // anti-loop bound — after a reset the cursor re-syncs to the live ring's last_seq (say 2); the next
  // poll's last_seq is >= that (seq is monotonic within a process), so it returns false and cannot
  // re-trigger. At most ONE reset per actual restart — no thrash.
  assert.equal(shouldResetCursor(2, 2), false) // immediately after the reset, no new lines yet
  assert.equal(shouldResetCursor(7, 2), false) // ring grew normally afterward
})

test('collapse keys are unique across a mixed ring+disk buffer — a disk index must not collide with a ring seq (F8c/d fence)', () => {
  // Disk lines carry no `seq`. Under the OLD `${seq ?? rows.length}-${message}` scheme the disk 'X'
  // below lands at collapse-index 3 -> "3-X", and the ring 'X' has seq 3 -> "3-X": a DUPLICATE key,
  // which is what let React omit stale rows (F8c) and duplicate/misorder rows (F8d). Distinct ts so
  // nothing folds; this is the exact class the operator captured (`6-records_from_vm`, `7-…`).
  const disk = ['a', 'b', 'c', 'X', 'records_from_vm'].map((message, i) => ({
    ts: `2026-07-22T14:40:0${i}.000+05:30`, logger: 'r', level: 'INFO', ipo_id: '', message,
  }))
  const ring = ['p', 'q', 'X'].map((message, i) => ({
    ts: `2026-07-22T14:41:0${i}.000+05:30`, logger: 'r', level: 'INFO', ipo_id: '', message, seq: i + 1,
  }))
  const keys = collapse(disk.concat(ring)).map((r) => r.key)
  assert.equal(new Set(keys).size, keys.length) // ALL unique (old scheme produced "3-X" twice)
})

test('collapse keys survive an older page prepending — even when it merges into the front run (stability)', () => {
  // The front run is a single `start`; the older page ends with ANOTHER `start` that folds into it.
  // A first-entry key anchor would change here (the churn the amendment guards against); a
  // newest-entry anchor must not — only the count grows.
  const mk = (ts: string, message: string, seq?: number) => ({
    ts, logger: 'r', level: 'INFO', ipo_id: '', message, ...(seq != null ? { seq } : {}),
  })
  const current = [mk('2026-07-22T10:03:00.000+05:30', 'start'), mk('2026-07-22T10:04:00.000+05:30', 'done'), mk('2026-07-22T10:05:00.000+05:30', 'start', 1)]
  const beforeKeys = collapse(current).map((r) => r.key)
  const older = [mk('2026-07-22T10:01:00.000+05:30', 'boot'), mk('2026-07-22T10:02:00.000+05:30', 'start')]
  const afterKeys = new Set(collapse(prependOlder(older, current)).map((r) => r.key))
  for (const k of beforeKeys) assert.ok(afterKeys.has(k), `pre-existing key ${k} must survive the prepend`)
})

test('prependOlder de-dupes exact twins but keeps distinct same-ms events (over-dedup fix)', () => {
  const cur = [{ ts: 'T', logger: 'r', level: 'INFO', ipo_id: '', message: 'records_from_vm', count: 3, seq: 9 }]
  // a true twin: same payload as cur[0] except it has no `seq` (the disk copy) -> dropped, same ref
  const twin = [{ ts: 'T', logger: 'r', level: 'INFO', ipo_id: '', message: 'records_from_vm', count: 3 }]
  assert.equal(prependOlder(twin, cur), cur)
  // a DISTINCT event: identical ts/logger/message/ipo_id but a different extra (count) -> must be KEPT.
  // The old ts|logger|message|ipo_id seam key wrongly dropped it (silent loss).
  const distinct = [{ ts: 'T', logger: 'r', level: 'INFO', ipo_id: '', message: 'records_from_vm', count: 7 }]
  assert.equal(prependOlder(distinct, cur).length, 2)
})

test('resetForLevel resets EXACTLY the re-pull state and touches nothing else (F8b hard fence)', () => {
  const tail = {
    entries: [
      { ts: '2026-07-22T15:00:00.000+05:30', level: 'ERROR', logger: 'r', message: 'scheduler_cycle_failed', ipo_id: '', seq: 8 },
      { ts: '2026-07-22T15:01:00.000+05:30', level: 'ERROR', logger: 'r', message: 'stdin_refresh_failed', ipo_id: '', seq: 9 },
    ],
    last_seq: 9,
  }
  const s = resetForLevel(tail, null) // ring not thin → no backfill
  // every RESET field, asserted:
  assert.equal(s.entries, tail.entries) // buffer ← the fresh tail
  assert.equal(s.since, 9) // sinceRef ← ring last_seq
  assert.equal(s.oldestTs, '2026-07-22T15:00:00.000+05:30') // oldestTsRef ← the tail's oldest
  assert.equal(s.historyDone, false) // historyDoneRef reset (new level → new history to page)
  assert.equal(s.pinned, true) // pinnedRef reset (re-open at the bottom)
  // every PERSISTED field, asserted ABSENT — resetForLevel structurally cannot wipe the user's search,
  // scroll-restore, or expanded row (a stray reset would change this key set and fail the test):
  assert.deepEqual(Object.keys(s).sort(), ['entries', 'historyDone', 'oldestTs', 'pinned', 'since'])
  assert.equal('query' in s, false)
  assert.equal('restoreRef' in s, false)
  assert.equal('openKey' in s, false)

  // thin-ring backfill: the older disk page prepends; oldestTs follows it; the ring cursor is unchanged
  const backfill = [{ ts: '2026-07-22T09:00:00.000+05:30', level: 'ERROR', logger: 'r', message: 'boot_fail', ipo_id: '' }]
  const b = resetForLevel(tail, backfill)
  assert.equal(b.entries.length, 3) // 1 disk + 2 ring
  assert.equal(b.oldestTs, '2026-07-22T09:00:00.000+05:30')
  assert.equal(b.since, 9)
})

test('collapse folds warn/err made adjacent once the filter drops the INFO between them (F8b)', () => {
  // Two identical WARNs separated by INFO in the raw log; a warn+ filter removes the INFO, so they
  // become consecutive and collapse SHOULD fold them into one ×2 row (correct repeat-suppression).
  const raw = [
    { ts: 't1', level: 'WARNING', logger: 'r', message: 'overdue_listing_detected', ipo_id: 'a' },
    { ts: 't2', level: 'INFO', logger: 'r', message: 'scheduler_cycle_start', ipo_id: '' },
    { ts: 't3', level: 'WARNING', logger: 'r', message: 'overdue_listing_detected', ipo_id: 'a' },
  ]
  const filtered = filterEntries(raw, { level: 'warn', query: '' })
  assert.equal(filtered.length, 2) // the INFO dropped
  const rows = collapse(filtered)
  assert.equal(rows.length, 1) // the two WARNs, now adjacent, fold
  assert.equal(rows[0].count, 2)
})

test('levelParam builds the &level= fetch fragment (all → none)', () => {
  assert.equal(levelParam('all'), '')
  assert.equal(levelParam('warn'), '&level=warn')
  assert.equal(levelParam('err'), '&level=err')
})
