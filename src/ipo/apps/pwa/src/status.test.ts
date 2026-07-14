// v3 finding-④ — the awaiting-listing label names a SILENT resolution strand honestly instead of
// the reassuring-but-false "awaiting listing" that lets a stuck IPO hide. Pure-logic test over the
// ONE shared definition (status.ts), run via `node --test`, so the shipped label == the tested one.

import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { IPOListRow } from './api/types'
import { awaitingLabel } from './status.ts'

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
