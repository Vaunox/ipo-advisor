// v3 finding-④ — the awaiting-listing label names a SILENT resolution strand honestly instead of
// the reassuring-but-false "awaiting listing" that lets a stuck IPO hide. Pure-logic test over the
// ONE shared definition (status.ts), run via `node --test`, so the shipped label == the tested one.

import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { IPOListRow, StatusView } from './api/types'
import {
  DELAY_DISCLOSURE,
  REFRESH_MIN_VISIBLE_MS,
  awaitingLabel,
  fallbackStatus,
  refreshAck,
  refreshHold,
  syncChip,
} from './status.ts'
import type { AckSnapshot } from './status.ts'

function ymd(offsetDays: number): string {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() + offsetDays)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function row(o: { listing: number | null; overdue: boolean }): IPOListRow {
  return {
    ipo_id: 'x',
    name: 'X',
    segment: 'mainboard',
    issue_size_cr: null,
    ofs_fraction: null,
    issue_pe: null,
    peer_median_pe: null,
    open_date: ymd(-20),
    close_date: ymd(-10),
    listing_date: o.listing == null ? null : ymd(o.listing),
    verdict: 'APPLY',
    probability: 0.9,
    reason: '',
    watch: [],
    kill_flags: [],
    listing_overdue: o.overdue,
  }
}

test('on-track: closed-not-listed reads as awaiting, not a strand', () => {
  const r = awaitingLabel(row({ listing: null, overdue: false }))
  assert.equal(r.text, 'book closed · awaiting listing')
  assert.equal(r.overdue, false)
})

test('on-track: listed-without-outcome reads as outcome pending, not a strand', () => {
  const r = awaitingLabel(row({ listing: -2, overdue: false }))
  assert.equal(r.text, 'listed · outcome pending')
  assert.equal(r.overdue, false)
})

test('strand mode 1 (never resolved): names the resolution failure honestly', () => {
  const r = awaitingLabel(row({ listing: null, overdue: true }))
  assert.equal(r.text, 'listing overdue — resolution may have failed')
  assert.equal(r.overdue, true)
})

test('strand mode 2 (listed but never priced): names the missing outcome honestly', () => {
  const r = awaitingLabel(row({ listing: -2, overdue: true }))
  assert.equal(r.text, 'listing outcome overdue — price never recorded')
  assert.equal(r.overdue, true)
})

// v3 V3-1 — the three-state fallback indicator (must never look degraded in normal operation).
test('dark-ship (no VM configured) → no indicator', () => {
  assert.equal(fallbackStatus('local', null), null)
  assert.equal(fallbackStatus(null, null), null)
})

test('both stores from the VM → no indicator (stays quiet)', () => {
  assert.equal(fallbackStatus('vm', 'vm'), null)
})

test('VM down → the honest per-store split (records fresh vs context aging)', () => {
  const fb = fallbackStatus('local', 'local')
  assert.equal(fb?.text, 'on local — context aging') // records freshness is the "Updated …" timestamp
  assert.match(fb?.title ?? '', /records fresh from NSE/) // full per-store detail in the tooltip
  assert.match(fb?.title ?? '', /aging/)
})

test('partial fallback names the one store that fell back', () => {
  assert.equal(fallbackStatus('local', 'vm')?.text, 'records on local')
  assert.equal(fallbackStatus('vm', 'local')?.text, 'context aging')
})

// --- OP-2: the freshness chip shows "Refreshing…" ONLY for a genuine, client-knowable manual pull ---

// Deterministic time-format so text assertions don't depend on the runtime's Intl/timezone.
const FMT = (_iso: string): string => '10:29 AM'

function status(over: Partial<StatusView> = {}): StatusView {
  return {
    live_ingest: true,
    last_successful_ingest: '2026-07-20T10:29:00+05:30',
    last_attempt: '2026-07-20T10:29:00+05:30',
    last_attempt_ok: true,
    // OP-2 Phase 2: the app's-last-pull clock the chip now shows as "Checked HH:MM".
    checked_at: '2026-07-20T10:29:00+05:30',
    records_source: null,
    context_source: null,
    next_refresh_at: null,
    ...over,
  }
}

test('THE FLICKER BUG: a background poll (no manual refresh) reads Checked, NOT Refreshing', () => {
  // The exact OP-2 regression: bound to a real in-flight pull, a 5s /status re-poll (inFlight:false)
  // must read the honest freshness, never "Refreshing…". This is what useIsFetching() got wrong.
  const chip = syncChip({ isError: false, refreshInFlight: false, status: status() }, FMT)
  assert.equal(chip.text, 'Checked 10:29 AM')
  assert.equal(chip.state, 'ok')
  assert.doesNotMatch(chip.text, /Refreshing/)
})

test('a genuine manual refresh in flight reads Refreshing (busy)', () => {
  const chip = syncChip({ isError: false, refreshInFlight: true, status: status() }, FMT)
  assert.equal(chip.text, 'Refreshing…')
  assert.equal(chip.state, 'busy')
})

test('an in-flight manual pull shows Refreshing even over a failed newer pull', () => {
  const chip = syncChip(
    { isError: false, refreshInFlight: true, status: status({ last_attempt_ok: false }) },
    FMT,
  )
  assert.equal(chip.text, 'Refreshing…')
})

test('engine unreachable reads Reconnecting (err), and error wins over manual state', () => {
  const chip = syncChip({ isError: true, refreshInFlight: true, status: status() }, FMT)
  assert.equal(chip.text, 'Reconnecting…')
  assert.equal(chip.state, 'err')
})

test('a failed newer pull reads Checked … · retrying (warn), NOT Refreshing', () => {
  // The check clock (last successful pull) stays put — a failed pull never advances it — and the
  // `· retrying` suffix fires off last_attempt_ok. Regression fence for the degraded suffix.
  const chip = syncChip(
    { isError: false, refreshInFlight: false, status: status({ last_attempt_ok: false }) },
    FMT,
  )
  assert.equal(chip.text, 'Checked 10:29 AM · retrying')
  assert.equal(chip.state, 'warn')
})

test('a VM fallback composes the honest per-store suffix and turns the dot amber', () => {
  const chip = syncChip(
    {
      isError: false,
      refreshInFlight: false,
      status: status({ records_source: 'local', context_source: 'local' }),
    },
    FMT,
  )
  assert.match(chip.text, /Checked 10:29 AM · on local — context aging/)
  assert.equal(chip.state, 'warn') // an ok state degrades to warn on a local fallback
})

test('review #6: a reachable VM with no fresh data reads "Checked", never "retrying" or "refreshed"', () => {
  // `record_no_freshness` (reachable, no fresh NSE stamp) advances `checked_at` but leaves
  // `last_successful_ingest` null — "I checked at HH:MM" is true even when the VM had nothing fresh.
  // So the chip reads "Checked …", state ok — NO false "Refreshing…", NO false "· retrying". The
  // freshness lie review #6 guarded against (a false success-at-now) is on the DATA clock, untouched.
  const chip = syncChip(
    {
      isError: false,
      refreshInFlight: false,
      status: status({ last_successful_ingest: null, last_attempt_ok: true }),
    },
    FMT,
  )
  assert.equal(chip.text, 'Checked 10:29 AM')
  assert.equal(chip.state, 'ok') // NOT warn — the VM was reachable, this is not "retrying"
  assert.doesNotMatch(chip.text, /Refreshing|retrying/)
})

test('review #6: with a prior success + no fresh data, the chip keeps last-known, no "retrying"', () => {
  const chip = syncChip(
    { isError: false, refreshInFlight: false, status: status({ last_attempt_ok: true }) },
    FMT,
  )
  assert.equal(chip.text, 'Checked 10:29 AM') // last-known, never "· retrying"
  assert.equal(chip.state, 'ok')
})

// --- OP-2 Phase 2: the "Checked HH:MM" clock, its static tooltip, and the refresh acknowledgment ---

test('the primary clock is "Checked HH:MM" (the app pull), with a STATIC delay-disclosure tooltip', () => {
  const chip = syncChip({ isError: false, refreshInFlight: false, status: status() }, FMT)
  assert.equal(chip.text, 'Checked 10:29 AM') // the app's-last-pull clock, not the data's refreshed_at
  assert.equal(chip.title, DELAY_DISCLOSURE) // a static disclosure — never a second timestamp
  assert.doesNotMatch(chip.title, /\d{1,2}:\d{2}/) // no clock time leaked into the tooltip
})

// A resolved manual press acknowledges what actually changed. `advanced=true` (new data) resolves
// to "New data ✓"; `advanced=false` (the console case — checked, nothing newer) to "Up to date ✓".
test('ack: advanced=true resolves to "New data ✓" (busy state is not needed here)', () => {
  const chip = syncChip({ isError: false, refreshInFlight: false, ack: 'newdata', status: status() }, FMT)
  assert.equal(chip.text, 'New data ✓')
  assert.equal(chip.state, 'ok')
})

test('ack: advanced=false (nothing newer) resolves to "Up to date ✓", never a dead-looking no-op', () => {
  const chip = syncChip({ isError: false, refreshInFlight: false, ack: 'uptodate', status: status() }, FMT)
  assert.equal(chip.text, 'Up to date ✓')
  assert.equal(chip.state, 'ok')
})

test('ack: a failed refresh resolves to "Couldn\'t refresh" (warn), never a false "up to date"', () => {
  const chip = syncChip({ isError: false, refreshInFlight: false, ack: 'failed', status: status() }, FMT)
  assert.equal(chip.text, "Couldn't refresh")
  assert.equal(chip.state, 'warn')
})

test('ack precedence: an in-flight refresh still wins over an ack (busy > ack), error wins over both', () => {
  const busy = syncChip({ isError: false, refreshInFlight: true, ack: 'uptodate', status: status() }, FMT)
  assert.equal(busy.text, 'Refreshing…') // the beat runs first; the ack is the resolution AFTER it
  const err = syncChip({ isError: true, refreshInFlight: false, ack: 'uptodate', status: status() }, FMT)
  assert.equal(err.text, 'Reconnecting…')
})

test('an ack is a clean confirmation — it does NOT compose the VM-fallback suffix', () => {
  // The steady chip it settles back to carries the per-store detail; the transient ack stays clean.
  const chip = syncChip(
    {
      isError: false,
      refreshInFlight: false,
      ack: 'uptodate',
      status: status({ records_source: 'local', context_source: 'local' }),
    },
    FMT,
  )
  assert.equal(chip.text, 'Up to date ✓')
  assert.doesNotMatch(chip.text, /local|aging/)
})

// --- OP-2 Phase 2: the pure refreshAck classifier (before → after freshness snapshots) ---

function snap(over: Partial<AckSnapshot> = {}): AckSnapshot {
  return {
    checked_at: '2026-07-20T10:00:00+05:30',
    last_successful_ingest: '2026-07-20T10:00:00+05:30',
    last_attempt: '2026-07-20T10:00:00+05:30',
    last_attempt_ok: true,
    ...over,
  }
}

test('refreshAck: new NSE data (both clocks advance) → newdata', () => {
  const before = snap()
  const after = snap({
    checked_at: '2026-07-20T10:31:00+05:30',
    last_successful_ingest: '2026-07-20T10:31:00+05:30',
    last_attempt: '2026-07-20T10:31:00+05:30',
  })
  assert.equal(refreshAck(before, after), 'newdata')
})

test('refreshAck: a successful check with nothing newer (only the pull clock advances) → uptodate', () => {
  // The exact console signature: source=vm, advanced=false. checked_at moved; the data clock did not.
  const before = snap()
  const after = snap({ checked_at: '2026-07-20T10:31:00+05:30' })
  assert.equal(refreshAck(before, after), 'uptodate')
})

test('refreshAck: the check clock does NOT advance on a failed pull → failed, never up-to-date', () => {
  // A reachable pull that errored moves last_attempt + flips ok=false, but NOT checked_at. It must
  // classify as failed — never claim "Up to date", which would be a fresh lie replacing the old one.
  const before = snap()
  const after = snap({ last_attempt: '2026-07-20T10:31:00+05:30', last_attempt_ok: false })
  assert.equal(refreshAck(before, after), 'failed')
})

test('refreshAck: a debounced/coalesced press (nothing moved) → none — never claim a phantom check', () => {
  assert.equal(refreshAck(snap(), snap()), 'none')
  assert.equal(refreshAck(null, snap()), 'none') // status not loaded yet → no ack
})

// --- OP-2 Phase 2: no-layout-shift — every new label fits the reserved 16ch chip floor ---

test('no-shift: the new steady + ack labels all fit the reserved 16ch width (styles.css .syncstat-t)', () => {
  // The chip reserves a 16ch floor so the common flip never resizes it or nudges neighbours. Every
  // new label must fit within it. (The ✓ glyph's true visual width is a Fira-Code build check the
  // operator owns; this keys on character count, the width contract we can assert headlessly.)
  for (const label of ['Checked 10:29 AM', 'Refreshing…', 'New data ✓', 'Up to date ✓', "Couldn't refresh"]) {
    assert.ok(label.length <= 16, `"${label}" is ${label.length} chars — overruns the 16ch floor`)
  }
})

// --- OP-2: the manual-refresh min-duration hold (pure decision, no flaky timer test) ---

test('refreshHold: still pulling → keep waiting, do not clear', () => {
  assert.deepEqual(refreshHold(50, false), { clear: false, waitMs: 0 })
})

test('refreshHold: resolved after the beat → clear now', () => {
  assert.deepEqual(refreshHold(REFRESH_MIN_VISIBLE_MS + 10, true), { clear: true, waitMs: 0 })
})

test('refreshHold: resolved within the beat → hold out the remainder (never a sub-perceptible flash)', () => {
  const r = refreshHold(200, true, 600)
  assert.equal(r.clear, false)
  assert.equal(r.waitMs, 400) // 600 - 200
})
