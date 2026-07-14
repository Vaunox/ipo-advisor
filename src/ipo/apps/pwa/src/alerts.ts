// Alert retention selection (v3 BUG 2) — pure functions, no React/DOM, so they can be unit-tested
// under `node --test` (see alerts.test.ts) and reused verbatim by the alert center and the native-
// notification path. Centralizing them here means the tested logic IS the shipped logic — no second
// copy to drift.
//
// The rule: an alert is relevant while its IPO's outcome is UNRESOLVED (`alertRelevant` in status.ts
// — not yet listed). The engine's transition log is never pruned (it's the permanent per-IPO audit
// trail on the detail view); these functions produce a bounded VIEW over it.

import type { IPOListRow, VerdictTransition } from './api/types'
import { alertRelevant } from './status.ts'

// The ids of IPOs whose alerts are still relevant (on the board and not yet listed).
function relevanceSet(board: IPOListRow[]): Set<string> {
  return new Set(board.filter(alertRelevant).map((r) => r.ipo_id))
}

// Current APPLY signals, scoped to still-unresolved IPOs (a listed APPLY is History, not an alert).
export function currentApplyAlerts(board: IPOListRow[]): IPOListRow[] {
  return board.filter((r) => r.verdict === 'APPLY' && alertRelevant(r))
}

// The latest APPLY crossing per still-relevant IPO. Input is the transition log, most-recent-first
// (as the engine serves it), so the first crossing seen for an IPO is its latest — deduped, and any
// IPO that has listed or left the board is dropped. Bounded to actionable IPOs.
export function relevantApplyCrossings(
  transitions: VerdictTransition[],
  board: IPOListRow[],
): VerdictTransition[] {
  const relevant = relevanceSet(board)
  const latest = new Map<string, VerdictTransition>()
  for (const t of transitions) {
    if (!t.crossed_into_apply || !relevant.has(t.ipo_id)) continue
    if (!latest.has(t.ipo_id)) latest.set(t.ipo_id, t)
  }
  return [...latest.values()]
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
