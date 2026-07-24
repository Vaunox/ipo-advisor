// Alert retention selection (v3 BUG 2) — pure functions, no React/DOM, so they can be unit-tested
// under `node --test` (see alerts.test.ts) and reused verbatim by the alert center and the native-
// notification path. Centralizing them here means the tested logic IS the shipped logic — no second
// copy to drift.
//
// The rule: an alert is relevant while its IPO's outcome is UNRESOLVED (`alertRelevant` in status.ts
// — not yet listed). The engine's transition log is never pruned (it's the permanent per-IPO audit
// trail on the detail view); these functions produce a bounded VIEW over it.
//
// F12 splits two distinct notions that used to be conflated:
//   * RETENTION relevance (`alertRelevant` = not-yet-listed) still bounds the seen-sets, the native-
//     notification frontier and the prune — untouched, exactly as OP-3/BUG-2 built them.
//   * DISPLAY relevance for the bell is NARROWER (`statusLabel().live` = book still open), because an
//     APPLY signal is actionable only while you can still apply. Post-close tracking belongs to
//     Allotment (V3-6) + History, not the live bell (F4). This is a display filter ONLY.

import type { IPOListRow, StatusView, VerdictTransition } from './api/types'
import type { AlertCondition } from './status.ts'
import { alertRelevant, degradedConditions, statusLabel } from './status.ts'

// The ids of IPOs whose alerts are still relevant (on the board and not yet listed).
function relevanceSet(board: IPOListRow[]): Set<string> {
  return new Set(board.filter(alertRelevant).map((r) => r.ipo_id))
}

// All transitions (any type) whose IPO is still relevant — used by the notification path to bound
// both its fire-candidates and its persisted seen-frontier.
export function relevantTransitions(
  transitions: VerdictTransition[],
  board: IPOListRow[],
): VerdictTransition[] {
  const relevant = relevanceSet(board)
  return transitions.filter((t) => relevant.has(t.ipo_id))
}

// Prune a persisted list of ipo_ids (e.g. the alerts-seen set) to those still relevant, so it can't
// grow without bound as IPOs list and leave.
export function pruneRelevantIds(ids: string[], board: IPOListRow[]): string[] {
  const relevant = relevanceSet(board)
  return ids.filter((id) => relevant.has(id))
}

// The persisted-seen-set prune, guarded for the cold start. NEVER prune against an EMPTY board: on
// launch the board prop is `[]` for the first render(s) (the query hasn't resolved), and pruning
// then matches nothing, wipes the whole persisted set, and re-lights the badge for alerts the user
// had already cleared — the seen-state does not survive a restart. Skipping is safe because an empty
// board also cannot GROW the set: ids only ever enter it from crossings, derived from these same
// rows. So "no rows" means "nothing to add and nothing to judge against" — wait for data.
export function pruneSeenIds(ids: string[], board: IPOListRow[]): string[] {
  if (board.length === 0) return ids
  return pruneRelevantIds(ids, board)
}

// F12: the dismissed-crossings prune. Dismissed keys are `ipo_id@asof`; keep a key while its IPO is
// still relevant (not yet listed), so the durable dismissed set can't grow without bound. Cold-start-
// guarded exactly like pruneSeenIds — never prune against an empty board (would wipe the set and
// un-dismiss everything on the next restart). Bounding by RETENTION relevance (not the narrower live
// display) matches pruneSeenIds and keeps a key a few extra days until listing; a closed IPO's key is
// simply never displayed in the meantime (liveApplyCrossings already excludes it).
export function pruneDismissedKeys(keys: string[], board: IPOListRow[]): string[] {
  if (board.length === 0) return keys
  const relevant = relevanceSet(board)
  return keys.filter((k) => relevant.has(ipoIdOf(k)))
}

// The crossing identity used for dismiss — same `ipo_id@asof` scheme the native notifier keys on
// (a SEPARATE set from notifiedCrossings, which the notifier auto-advances every cycle; reusing it
// would make dismissals evaporate). A hypothetical re-cross carries a new `asof` → a new key → it
// correctly re-lights, so dismiss is per-event and safe. Since a re-cross can't realistically happen
// (subscription only accumulates while a book is open; `decision_asof` freezes at close — F11
// determinism), a dismissed key stays the latest → permanently dismissed.
export const crossingKey = (t: { ipo_id: string; asof: string }): string => `${t.ipo_id}@${t.asof}`
const ipoIdOf = (key: string): string => key.slice(0, key.indexOf('@'))

// F12/F4: the APPLY crossings shown in the bell — latest per IPO, scoped to books that are still
// OPEN (`statusLabel().live`: Open / Closes-Today). Input is the transition log most-recent-first (as
// the engine serves it), so the first crossing seen for an IPO is its latest. NARROWER than the old
// relevantApplyCrossings (which kept awaiting-listing): once the book closes the signal is no longer
// actionable and drops out of the bell (SBI Funds Management, etc.).
export function liveApplyCrossings(
  transitions: VerdictTransition[],
  board: IPOListRow[],
): VerdictTransition[] {
  const live = new Set(board.filter((r) => statusLabel(r).live).map((r) => r.ipo_id))
  const latest = new Map<string, VerdictTransition>()
  for (const t of transitions) {
    if (!t.crossed_into_apply || !live.has(t.ipo_id)) continue
    if (!latest.has(t.ipo_id)) latest.set(t.ipo_id, t)
  }
  return [...latest.values()]
}

// One bell item: a dismissible EVENT (an APPLY crossing that happened once) or an undismissible
// CONDITION (a degraded state that persists until it clears). The discriminated union enforces (F12
// f) structurally — `dismissible = item.kind === 'event'`, one predicate, no scattered guards.
export interface AlertEvent {
  kind: 'event'
  key: string // crossing key `ipo_id@asof` — the dismiss identity
  ipo_id: string
  name: string
  probability: number | null
  asof: string
}
export type AlertItem = AlertEvent | AlertCondition

// The whole bell state, computed PURELY so the split / dismiss / badge / F4 rules are node-testable
// and can't drift from the shipped panel. `badge` is the unread-EVENT count; `flag` is the worst
// condition severity (null when no condition) — when `flag` is set the badge shows "!" REPLACING the
// count (F12 d), and the count returns once the condition clears.
export interface AlertFeed {
  items: AlertItem[]
  badge: number
  flag: 'amber' | 'red' | null
}

const SEV_RANK: Record<'amber' | 'red', number> = { amber: 1, red: 2 }

export function buildAlertFeed(
  crossings: VerdictTransition[],
  board: IPOListRow[],
  status: StatusView | undefined,
  isError: boolean,
  dismissed: Set<string>,
  seen: Set<string>,
): AlertFeed {
  const conditions = [...degradedConditions(status, isError)].sort(
    (a, b) => SEV_RANK[b.severity] - SEV_RANK[a.severity],
  )
  const events: AlertEvent[] = liveApplyCrossings(crossings, board)
    .filter((t) => !dismissed.has(crossingKey(t)))
    .map((t) => ({
      kind: 'event',
      key: crossingKey(t),
      ipo_id: t.ipo_id,
      name: t.name,
      probability: t.probability,
      asof: t.asof,
    }))
  // Conditions on top (the persistent signal, worst-first), events below. Because dismiss filters the
  // events branch ONLY, and conditions are regenerated here every call, a condition can never be
  // dismissed — (f) holds by construction. Unread counts LIVE, NON-DISMISSED events, so dismissing
  // everything leaves badge 0 (no stale count) even if `seen` never saw those ids.
  const items: AlertItem[] = [...conditions, ...events]
  const badge = events.filter((e) => !seen.has(e.ipo_id)).length
  const flag = conditions.length ? (conditions.some((c) => c.severity === 'red') ? 'red' : 'amber') : null
  return { items, badge, flag }
}
