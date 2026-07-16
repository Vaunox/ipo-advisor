// Pure view helpers for the debug console (v3 V3-16) — filtering, repeat-suppression, and the
// legible `detail` string. Kept out of the component so they're unit-testable (node --test) exactly
// as they ship, like alerts.ts / status.ts. No React, no I/O.

import type { LogEntry } from '../api/types'

// Fields shown in their own column (or internal) — never repeated inside the `detail` string.
const OMIT = new Set(['ts', 'level', 'message', 'logger', 'seq', 'ipo_id'])

export type LevelClass = 'info' | 'warn' | 'err'

// Map a level name to the terminal's three colour classes: INFO green · WARN amber · ERROR red.
// CRITICAL folds into err; anything unrecognised is treated as INFO (neutral), never dropped.
export function levelClass(level: string | undefined): LevelClass {
  const l = (level ?? '').toUpperCase()
  if (l.startsWith('ERR') || l === 'CRITICAL') return 'err'
  if (l.startsWith('WARN')) return 'warn'
  return 'info'
}

// The fixed-width level code shown in the `level` column (INFO / WARN / ERR!).
export function levelCode(level: string | undefined): string {
  const c = levelClass(level)
  return c === 'err' ? 'ERR!' : c === 'warn' ? 'WARN' : 'INFO'
}

// Render an entry's `extra` fields as a legible "key=value · key=value" string — the specifics,
// dimmed, with the columned/internal fields removed so the event name stays prominent.
export function formatDetail(entry: LogEntry): string {
  const parts: string[] = []
  for (const [k, v] of Object.entries(entry)) {
    if (OMIT.has(k) || v == null) continue
    parts.push(`${k}=${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
  }
  return parts.join(' · ')
}

export interface FilterOpts {
  level: 'all' | LevelClass
  query: string
}

// Filter by level chip and a free-text query over the event name + ipo_id (the "filterable by
// ipo_id / level / event" locked requirement). Empty query matches everything.
export function filterEntries(entries: LogEntry[], { level, query }: FilterOpts): LogEntry[] {
  const q = query.trim().toLowerCase()
  return entries.filter((e) => {
    if (level !== 'all' && levelClass(e.level) !== level) return false
    if (!q) return true
    return `${e.message ?? ''} ${e.ipo_id ?? ''}`.toLowerCase().includes(q)
  })
}

export interface ConsoleRow {
  entry: LogEntry
  count: number // 1 normally; N when a run of identical events was folded (e.g. fetch_retry ×47)
  key: string
}

// Repeat-suppression: fold a RUN of consecutive entries with the same event identity (level +
// message + ipo_id) into ONE row carrying the count — so a failure loop is one counted line, not a
// 47-line flood that evicts history. Different interleaved events break the run. The latest entry's
// detail is kept (e.g. the most recent attempt).
export function collapse(entries: LogEntry[]): ConsoleRow[] {
  const rows: ConsoleRow[] = []
  for (const entry of entries) {
    const last = rows[rows.length - 1]
    const same =
      last != null &&
      last.entry.message === entry.message &&
      (last.entry.level ?? '') === (entry.level ?? '') &&
      (last.entry.ipo_id ?? '') === (entry.ipo_id ?? '')
    if (same) {
      last.count += 1
      last.entry = entry // keep the latest detail
    } else {
      rows.push({ entry, count: 1, key: `${entry.seq ?? rows.length}-${entry.message ?? ''}` })
    }
  }
  return rows
}

// The clock shown in the `ts` column: HH:MM:SS.mmm sliced out of the ISO timestamp (already IST from
// the engine). Falls back to the raw value if it isn't the expected shape.
export function shortTs(ts: string | undefined): string {
  if (!ts) return ''
  const t = ts.slice(11, 23)
  return t.length >= 8 ? t : ts
}

// The live tail's accumulation step: append the newly-polled lines (fetched via the `since` cursor,
// so no overlap) and keep only the newest `max` — a constant-memory client buffer that never grows
// unbounded no matter how long the console stays open. Empty `next` leaves the buffer untouched.
export function appendCapped(prev: LogEntry[], next: LogEntry[], max: number): LogEntry[] {
  if (next.length === 0) return prev
  const merged = prev.concat(next)
  return merged.length > max ? merged.slice(merged.length - max) : merged
}

// Identity used to stitch the ring→disk seam. NOT `seq` — that's ring-only (the same event on disk
// has no seq), so a ring line and its disk twin would look different. ts+logger+message+ipo_id is
// effectively unique at microsecond ts resolution, and matches across both sources.
function entryKey(e: LogEntry): string {
  return `${e.ts ?? ''}|${e.logger ?? ''}|${e.message ?? ''}|${e.ipo_id ?? ''}`
}

// Scroll-back stitch: prepend an older disk page ahead of the current buffer, dropping any entry
// already shown (the boundary line overlaps because the `before` cursor is inclusive). So the one
// continuous timeline — ring flowing into disk — has NO duplicate and NO gap at the seam. Returns
// the same array reference when nothing new is older (lets the caller detect "history exhausted").
export function prependOlder(older: LogEntry[], current: LogEntry[]): LogEntry[] {
  if (older.length === 0) return current
  const seen = new Set(current.map(entryKey))
  const fresh = older.filter((e) => !seen.has(entryKey(e)))
  return fresh.length === 0 ? current : fresh.concat(current)
}
