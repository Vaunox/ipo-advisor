// IPO lifecycle status — ONE definition, shared by the Live board, the alert center, and the
// native-notification path. Extracted from Live.tsx (v3 BUG 2) so relevance is computed identically
// everywhere: a second, drifting copy of "is this IPO still relevant" is exactly how retention bugs
// are born.

import type { IPOListRow, StatusView } from './api/types'

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
    (recLocal ? 'records fresh from NSE' : 'records still served from the VM') +
    '; ' +
    (ctxLocal
      ? 'context is last-known and aging (cannot refresh without the VM)'
      : 'context still served from the VM')
  return { text, title }
}

// v3 BUG 1 / OP-2 — the ONE data-state chip's state+text+title, as a PURE decision so it is
// node --test'd and can never drift from the shipped chip. The load-bearing OP-2 change: "Refreshing…"
// is bound to `refreshInFlight` — a GENUINE, client-knowable manual pull (the shell-triggered
// refresh) — NEVER `useIsFetching()`. A 5s background /status re-poll is a local read, not an NSE
// pull, and must not read as one; an automatic pull the client cannot observe stays silent and just
// advances "Updated HH:MM". "Updated …" freshness (BUG-1) is untouched — it is still the last
// *successful* pull.
export type SyncState = 'err' | 'busy' | 'ok' | 'warn'
export interface SyncChipInput {
  isError: boolean // health query errored (engine unreachable)
  refreshInFlight: boolean // a manual, min-duration-held refresh is genuinely in flight
  status: StatusView | undefined
}
export interface SyncChip {
  state: SyncState
  text: string
  title: string
  dot: string
}

export const istTimeOf = (iso: string): string =>
  new Date(iso).toLocaleTimeString('en-US', {
    timeZone: 'Asia/Kolkata',
    hour12: true,
    hour: 'numeric',
    minute: '2-digit',
  })

export function syncChip(
  { isError, refreshInFlight, status: s }: SyncChipInput,
  fmt: (iso: string) => string = istTimeOf,
): SyncChip {
  const updated = s?.last_successful_ingest ? fmt(s.last_successful_ingest) : null
  let state: SyncState
  let text: string
  let title: string
  if (isError) {
    state = 'err'
    text = 'Reconnecting…'
    title = "Couldn't reach the engine — retrying automatically"
  } else if (refreshInFlight) {
    state = 'busy'
    text = 'Refreshing…'
    title = 'Refreshing from the live feed…'
  } else if (s && s.live_ingest === false) {
    state = 'ok'
    text = 'Live'
    title = 'No live NSE feed configured in this build'
  } else if (updated && s?.last_attempt_ok === false) {
    state = 'warn'
    text = `Updated ${updated} · retrying`
    title = `Last successful NSE pull ${updated} IST — a newer pull failed; retrying automatically`
  } else if (updated) {
    state = 'ok'
    text = `Updated ${updated}`
    title = `Last successful NSE pull ${updated} IST`
  } else {
    state = s?.last_attempt_ok === false ? 'warn' : 'ok'
    text = 'Awaiting first update…'
    title = 'No successful NSE pull yet — fetching'
  }

  // Compose the data-plane fallback into THIS one chip (never a second, contradicting chip): silent
  // unless a store fell back from a configured VM, then the honest per-store suffix + amber dot.
  const fb = s ? fallbackStatus(s.records_source, s.context_source) : null
  if (fb) {
    if (state === 'ok') state = 'warn'
    text = `${text} · ${fb.text}`
    title = `${title} · ${fb.title}`
  }
  // Tooltip-only next-refresh hint (only when the engine can honestly predict it).
  if (s?.next_refresh_at) title = `${title} · next refresh ~${fmt(s.next_refresh_at)} IST`

  const dot =
    state === 'err'
      ? 'sync err'
      : state === 'warn'
        ? 'sync warn'
        : state === 'busy'
          ? 'sync on'
          : 'sync'
  return { state, text, title, dot }
}

// OP-2: the manual-refresh feedback beat. "Refreshing…" holds for at least this even if the pull
// resolves faster (never a sub-perceptible flash); a slower pull holds until it resolves. A named
// constant so the beat is tunable in one place.
export const REFRESH_MIN_VISIBLE_MS = 600

// Pure min-duration decision the RefreshContext drives (kept out of a flaky setTimeout test): given
// ms since the manual click and whether the pull has resolved, may "Refreshing…" clear now, or how
// long to hold. Not-resolved → keep waiting (on the resolve, not a timer); resolved-after-beat →
// clear; resolved-within-beat → hold out the remainder.
export function refreshHold(
  elapsedMs: number,
  resolved: boolean,
  minMs: number = REFRESH_MIN_VISIBLE_MS,
): { clear: boolean; waitMs: number } {
  if (!resolved) return { clear: false, waitMs: 0 }
  const remaining = minMs - elapsedMs
  if (remaining <= 0) return { clear: true, waitMs: 0 }
  return { clear: false, waitMs: remaining }
}
