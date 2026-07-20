// GATE low L3 — a date-only `YYYY-MM-DD` must display as its intended calendar day in ANY browser
// timezone. The bug: `new Date("2026-07-16")` parses as midnight UTC, so a browser behind UTC (the
// Americas) rendered the previous day. `parseDateOnly` pins to LOCAL midnight instead. Run via
// `node --test`.
//
// PROOF SHAPE — two layers, because Node caches TZ at startup (unlike Python's mid-run time.tzset()):
//   1. In-file, tz-INDEPENDENT invariants that run on every runner (incl. the UTC CI box): the
//      helper builds LOCAL midnight, whose local components are the input in any zone; the naive
//      parse is UTC-anchored. Plus the byte-identical migration proof for Live's fmtOpen.
//   2. A child `node` process spawned with TZ=America/Los_Angeles that exercises the real helper and
//      asserts it yields day 16 while the naive parse yields 15 — the faithful "force a US zone"
//      witness, which gates even on the UTC CI runner. (Node honours the TZ env var at startup on
//      every OS, so this runs on both Windows dev and Linux CI.)

import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { test } from 'node:test'
import { formatDateOnly, parseDateOnly } from './dates.ts'

const ISO = '2026-07-16' // a Thursday; nothing special, just a fixed date

// --- Layer 1: tz-independent invariants (run on any runner) ----------------------------------------

test('parseDateOnly builds LOCAL midnight, so its calendar day is the input in any tz', () => {
  const d = parseDateOnly(ISO)
  assert.equal(d.getFullYear(), 2026)
  assert.equal(d.getMonth(), 6) // July (0-based)
  assert.equal(d.getDate(), 16)
  assert.equal(d.getHours(), 0) // local midnight, not UTC midnight
  assert.equal(d.getTime(), new Date(2026, 6, 16).getTime()) // == the local-midnight reference
})

test('the naive new Date(YYYY-MM-DD) is UTC-anchored — the parse this bug came from', () => {
  const naive = new Date(ISO)
  assert.equal(naive.getUTCHours(), 0) // midnight UTC
  assert.equal(naive.getUTCDate(), 16)
  assert.equal(naive.getTime(), Date.UTC(2026, 6, 16))
  // West of UTC the two parses land on different calendar days; the child-process test below proves it.
})

test('formatDateOnly reproduces the pre-migration inline expressions byte-for-byte', () => {
  // Live.fmtOpen was `new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', {weekday,day,month})`.
  const liveOpts: Intl.DateTimeFormatOptions = { weekday: 'short', day: 'numeric', month: 'short' }
  assert.equal(
    formatDateOnly(ISO, liveOpts),
    new Date(ISO + 'T00:00:00').toLocaleDateString('en-IN', liveOpts),
  )
  // Allotment.fmtDate's options, likewise reproduced (only the buggy `new Date(iso)` parse changed).
  const allotOpts: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short', year: 'numeric' }
  assert.equal(
    formatDateOnly(ISO, allotOpts),
    new Date(ISO + 'T00:00:00').toLocaleDateString('en-IN', allotOpts),
  )
})

// --- Layer 2: the forced-US-timezone witness (child process; gates on the UTC CI runner) -----------

test('under TZ=America/Los_Angeles the helper keeps the day; the naive parse shifts it back', () => {
  const datesUrl = new URL('./dates.ts', import.meta.url).href
  const script =
    `const { parseDateOnly } = await import(${JSON.stringify(datesUrl)});` +
    `process.stdout.write(JSON.stringify({` +
    ` helper: parseDateOnly(${JSON.stringify(ISO)}).getDate(),` +
    ` naive: new Date(${JSON.stringify(ISO)}).getDate() }));`
  const out = execFileSync(process.execPath, ['--input-type=module', '-e', script], {
    env: { ...process.env, TZ: 'America/Los_Angeles' },
    encoding: 'utf8',
  })
  const { helper, naive } = JSON.parse(out) as { helper: number; naive: number }
  assert.equal(helper, 16) // the fix: the intended day, unshifted by the US local zone
  assert.equal(naive, 15) // the bug: the naive parse lands a day early west of UTC
})
