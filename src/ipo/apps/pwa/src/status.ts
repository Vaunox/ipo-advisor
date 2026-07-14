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
