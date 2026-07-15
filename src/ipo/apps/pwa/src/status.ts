// IPO lifecycle status — ONE definition, shared by the Live board, the alert center, and the
// native-notification path. Extracted from Live.tsx (v3 BUG 2) so relevance is computed identically
// everywhere: a second, drifting copy of "is this IPO still relevant" is exactly how retention bugs
// are born.

import type { IPOListRow } from './api/types'

export const midnight = (d: string): Date => new Date(d + 'T00:00:00')
export const today = (): Date => {
  const t = new Date()
  t.setHours(0, 0, 0, 0)
  return t
}

// Display status + two flags: `live` (the bidding window is open — Open / Closes-Today) and
// `closesToday`. Verbatim behavior from the original Live.tsx helper.
export function statusLabel(row: IPOListRow): { text: string; live: boolean; closesToday: boolean } {
  const t = today()
  const open = midnight(row.open_date)
  const close = midnight(row.close_date)
  const listing = row.listing_date ? midnight(row.listing_date) : null
  const closesToday = !listing && +close === +t
  if (listing && listing <= t) return { text: 'Listed', live: false, closesToday: false }
  if (close < t) return { text: 'Closed', live: false, closesToday: false }
  if (closesToday) return { text: 'CLOSES TODAY', live: true, closesToday: true }
  if (open <= t) return { text: 'Open', live: true, closesToday: false }
  return { text: 'Upcoming', live: false, closesToday: false }
}

// True once an IPO has listed (its listing day is here) — the point its outcome is resolved.
export function isListed(row: IPOListRow): boolean {
  const listing = row.listing_date ? midnight(row.listing_date) : null
  return listing != null && listing <= today()
}

// Alert retention (v3 BUG 2): an alert stays relevant while the IPO's outcome is UNRESOLVED — not
// merely while it is still biddable. Open / Closes-Today / Awaiting-listing (Closed but not yet
// listed) all keep the alert, because after the book closes the user has applied and is waiting on
// allotment + the listing outcome — arguably when they care most. Only a Listed IPO (outcome known,
// now History) drops out. This stays coherent with the Allotment tab (V3-6), which exists to serve
// exactly that post-close, pre-listing window. Awaiting-listing is a short bounded window (~3 days
// under T+3), so relevance is extended by a few days, not indefinitely.
export function alertRelevant(row: IPOListRow): boolean {
  return !isListed(row)
}

// Label for the History "Awaiting listing outcome" section (v3 finding-④). When the backend flags
// `listing_overdue` (a SILENT strand — the Live→History resolution should have completed but hasn't),
// the label names the strand honestly instead of the reassuring-but-false "awaiting listing" — which
// is exactly the lie that lets a stuck IPO hide. `overdue` drives the warning badge. One definition,
// shared, tested (status.test.ts) — never a second drifting copy.
export function awaitingLabel(row: IPOListRow): { text: string; overdue: boolean } {
  if (row.listing_overdue) {
    return {
      text: isListed(row)
        ? 'listing outcome overdue — price never recorded'
        : 'listing overdue — resolution may have failed',
      overdue: true,
    }
  }
  return {
    text: isListed(row) ? 'listed · outcome pending' : 'book closed · awaiting listing',
    overdue: false,
  }
}

// v3 V3-1 — the data-plane fallback indicator, composed into the ONE sync chip (never a second chip).
// It speaks ONLY when degraded, and renders the per-store distinction rather than a blanket status:
//   * no VM configured (context_source === null, "dark-ship") → null: normal operation, no indicator;
//   * both stores from the VM → null: all good, stay quiet;
//   * a store fell back to local → the honest split — records fresh (a real NSE re-scrape) vs context
//     last-known-aging (the Upstox token is on the VM, so context can't refresh until it returns).
// One shared, tested definition (status.test.ts) so the chip text can't drift from the truth.
export function fallbackStatus(
  recordsSource: string | null,
  contextSource: string | null,
): { text: string; title: string } | null {
  if (contextSource == null) return null // dark-ship: no VM — must not look degraded
  const recLocal = recordsSource === 'local'
  const ctxLocal = contextSource === 'local'
  if (!recLocal && !ctxLocal) return null // both served from the VM — stay quiet
  // Kept short so it composes into the header chip without crowding it (min window 1040px). The
  // "Updated …" timestamp already carries records freshness; the suffix flags only what the user
  // can't infer — that we're on local and, distinctly, that context is aging (records aren't flagged,
  // so they read as fine). The full per-store detail is in the title/tooltip.
  const text = recLocal && ctxLocal
    ? 'on local — context aging'
    : recLocal
      ? 'records on local'
      : 'context aging'
  const title =
    'VM unreachable — ' +
    (recLocal ? 'records re-scraped fresh from NSE' : 'records still served from the VM') +
    '; ' +
    (ctxLocal
      ? 'context is last-known and aging (cannot refresh without the VM)'
      : 'context still served from the VM')
  return { text, title }
}
