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

// F12 — the ONE degraded-state taxonomy, shared by the sync chip and the alert bell so the two can
// never drift (formerly `fallbackStatus`, which composed the VM split onto the chip as a suffix).
// The chip now holds only "Checked HH:MM" + acks and every degraded state surfaces HERE as its own
// bell entry — one per condition (F12 e), plain-English, severity-coloured (amber = degraded but
// working, red = broken). `isError` (the local engine unreachable) is the sole red condition AND the
// one degraded state the chip keeps its own presence for ("Reconnecting…"), because there the chip's
// own "I checked at…" claim can no longer be verified — the most serious condition gets the most
// prominence (one taxonomy, two presentations; not an inconsistency, proportionality).
//
// "server" is the user-facing word for the VM everywhere here; the internal source slugs the engine
// reports (`records_source`/`context_source` = 'vm' | 'local' | null) are unchanged.
export interface AlertCondition {
  kind: 'condition'
  key: string // stable slug — never a per-event id; a condition is never dismissible (F12 f)
  severity: 'amber' | 'red'
  title: string
  detail: string
}

export function degradedConditions(
  status: StatusView | undefined,
  isError: boolean,
): AlertCondition[] {
  // Engine unreachable SUBSUMES the source-derived states: the (now stale) status fields can't be
  // trusted and nothing works, so it stands alone as the single red condition rather than stacking
  // amber suffixes under it.
  if (isError) {
    return [
      {
        kind: 'condition',
        key: 'engine-down',
        severity: 'red',
        title: 'App not responding',
        detail: "The app's data service isn't answering. It's reconnecting automatically.",
      },
    ]
  }
  if (!status) return []
  const out: AlertCondition[] = []
  if (status.last_attempt_ok === false) {
    out.push({
      kind: 'condition',
      key: 'refresh-failed',
      severity: 'amber',
      title: 'Refresh failed',
      detail: "The last update didn't go through. It will retry on the next cycle — or refresh now.",
    })
  }
  // Dark-ship (no VM configured) must never look degraded: context_source === null means no VM at all.
  if (status.context_source != null) {
    if (status.records_source === 'local') {
      out.push({
        kind: 'condition',
        key: 'server-unreachable',
        severity: 'amber',
        title: 'Server unreachable',
        detail: 'Live data is coming from a local backup source and stays current.',
      })
    }
    if (status.context_source === 'local') {
      out.push({
        kind: 'condition',
        key: 'context-aging',
        severity: 'amber',
        title: 'Market context aging',
        detail: "Valuation context can't refresh until the server is back.",
      })
    }
  }
  return out
}

// v3 BUG 1 / OP-2 — the ONE data-state chip's state+text+title, as a PURE decision so it is
// node --test'd and can never drift from the shipped chip. The load-bearing OP-2 change: "Refreshing…"
// is bound to `refreshInFlight` — a GENUINE, client-knowable manual pull (the shell-triggered
// refresh) — NEVER `useIsFetching()`. A 5s background /status re-poll is a local read, not an NSE
// pull, and must not read as one; an automatic pull the client cannot observe stays silent and just
// advances "Updated HH:MM". "Updated …" freshness (BUG-1) is untouched — it is still the last
// *successful* pull.
export type SyncState = 'err' | 'busy' | 'ok' | 'warn'

// OP-2 Phase 2: the transient post-refresh acknowledgment. A manual refresh resolves into a brief,
// HONEST confirmation keyed on what actually changed — and NEVER claims a check that didn't happen:
//   * 'newdata'  → new NSE data arrived (the VM's data clock moved) → "New data ✓" then the new time
//   * 'uptodate' → the app checked but the VM had nothing newer (the console's advanced=false case)
//   * 'failed'   → a reachable pull errored (last_attempt moved, ok=false) → "Couldn't refresh"
//   * 'none'     → nothing observable moved (a debounced/coalesced press ran no cycle) → NO ack
export type RefreshAck = 'none' | 'newdata' | 'uptodate' | 'failed'

// The minimal freshness fields the ack decision reads (a subset of StatusView), snapshotted at the
// manual-press moment (`before`) and again when the pull resolves (`after`).
export interface AckSnapshot {
  checked_at: string | null
  last_successful_ingest: string | null
  last_attempt: string | null
  last_attempt_ok: boolean | null
}

export interface SyncChipInput {
  isError: boolean // health query errored (engine unreachable)
  refreshInFlight: boolean // a manual, min-duration-held refresh is genuinely in flight
  ack?: RefreshAck // OP-2 Phase 2: the transient post-refresh acknowledgment (default 'none')
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

// OP-2 Phase 2: the steady chip's tooltip is a STATIC market-data delay disclosure, not a second
// clock. The VM re-scrapes NSE on a fixed ~30-min loop, so healthy data is at most that stale; the
// real per-scrape refreshed_at stays in the V3-16 console (stdin_refresh_outcome), never duplicated
// here — a second timestamp confuses more than it informs, and users have no VM model. A VM outage
// is NOT hedged here: it flips to the local scraper and the chip says so via the fallbackStatus
// suffix, so the app self-heals and announces it. Mirrors the standard market-data disclosure.
export const DELAY_DISCLOSURE = 'Quotes data may be delayed up to 30 minutes'

export function syncChip(
  { isError, refreshInFlight, ack = 'none', status: s }: SyncChipInput,
  fmt: (iso: string) => string = istTimeOf,
): SyncChip {
  // OP-2 Phase 2: the primary clock is the app's-last-successful-PULL wall-clock ("Checked HH:MM"),
  // NOT the served data's own timestamp. "When did my app last get data" maps onto the action the
  // user just took (Refresh = re-pull); the data's refreshed_at is VM plumbing they have no model
  // for, so it is deliberately NOT surfaced here (it stays in the V3-16 console).
  const checked = s?.checked_at ? fmt(s.checked_at) : null
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
  } else if (ack === 'newdata') {
    // The pull genuinely advanced — resolve to the updated time, not "up to date" (the steady chip
    // below already shows the new "Checked HH:MM"); this is the brief positive confirmation.
    state = 'ok'
    text = 'New data ✓'
    title = DELAY_DISCLOSURE
  } else if (ack === 'uptodate') {
    // The console's advanced=false case: the app DID check, the VM just had nothing newer. This is
    // the whole point of Phase 2 — a successful "nothing new" pull now acknowledges instead of
    // resolving silently and reading as a dead button.
    state = 'ok'
    text = 'Up to date ✓'
    title = DELAY_DISCLOSURE
  } else if (ack === 'failed') {
    state = 'warn'
    text = "Couldn't refresh"
    title = 'A refresh attempt failed — retrying automatically'
  } else if (s && s.live_ingest === false) {
    state = 'ok'
    text = 'Live'
    title = 'No live NSE feed configured in this build'
  } else if (checked) {
    // F12: `last_attempt_ok === false` no longer degrades the chip — the "Refresh failed" nuance is a
    // bell condition now (degradedConditions). "Checked HH:MM" is the last SUCCESSFUL check and stays
    // true regardless of a later failed attempt, so the chip is honest with no suffix.
    state = 'ok'
    text = `Checked ${checked}`
    title = DELAY_DISCLOSURE
  } else {
    // F12: honest at ANY duration — a working engine clears this in seconds; a persistent no-data
    // state means fetches are failing, which is itself a bell condition. So never wording that
    // implies it's about to resolve ("Awaiting…"/"fetching…"): just the fact.
    state = 'ok'
    text = 'No data yet'
    title = 'No successful pull yet'
  }

  // F12: every degraded state (the VM data-plane split AND the failed-pull nuance) moved to the bell
  // (degradedConditions), so nothing composes a suffix onto the chip — it holds ONE fixed width in
  // every state (styles.css `.syncstat-t` max-width:16ch). Only the next-refresh hint remains, and it
  // is TOOLTIP-only (never the visible text), so it can't widen the chip.
  const isAck = ack !== 'none' && !isError && !refreshInFlight
  if (s?.next_refresh_at && !isAck) title = `${title} · next refresh ~${fmt(s.next_refresh_at)} IST`

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

// OP-2 Phase 2: how long the post-refresh acknowledgment ("Up to date ✓" / "New data ✓") holds
// before the chip settles back to its steady "Checked HH:MM" — long enough to read, short enough
// not to linger. A named constant so the beat is tunable in one place (like REFRESH_MIN_VISIBLE_MS).
export const REFRESH_ACK_MS = 2000

// OP-2 Phase 2: classify what a resolved manual refresh should acknowledge, from before/after
// freshness snapshots. PURE so it is node-testable and can never drift from the shipped chip. The
// honesty rule: only the app's-pull clock (`checked_at`) advancing proves a check actually ran, so
// a debounced/coalesced press (nothing moved) gets NO ack — we never claim a check that didn't
// happen. See `RefreshAck` for the four outcomes.
export function refreshAck(before: AckSnapshot | null, after: AckSnapshot | null): RefreshAck {
  if (before == null || after == null) return 'none'
  if (after.checked_at !== before.checked_at) {
    // A successful check ran. New NSE data → the data clock also moved; else nothing was newer.
    return after.last_successful_ingest !== before.last_successful_ingest ? 'newdata' : 'uptodate'
  }
  // No successful check. A genuine fetch FAILURE moved last_attempt and flipped ok=false → say so.
  // Anything else (a coalesced press that ran no cycle) moved nothing → stay silent.
  if (after.last_attempt_ok === false && after.last_attempt !== before.last_attempt) return 'failed'
  return 'none'
}
