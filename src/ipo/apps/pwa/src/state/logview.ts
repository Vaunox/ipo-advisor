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

// Numeric rank of a level bucket for the MIN-level filter (F8b) — mirrors the server's `level_rank`:
// info=0 · warn=1 · err=2. "warn and above" is rank ≥ 1.
export function levelRank(c: LevelClass): number {
  return c === 'err' ? 2 : c === 'warn' ? 1 : 0
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

// Filter by level chip (MIN-level: `warn` keeps WARN *and* ERROR — F8b, matching the server so the
// chip never hides errors) and a free-text query over the event name + ipo_id. Empty query matches
// everything. Kept client-side as well as server-side: instant feedback during a re-pull + defence if
// the server param is ever dropped.
export function filterEntries(entries: LogEntry[], { level, query }: FilterOpts): LogEntry[] {
  const q = query.trim().toLowerCase()
  const floor = level === 'all' ? 0 : levelRank(level)
  return entries.filter((e) => {
    if (level !== 'all' && levelRank(levelClass(e.level)) < floor) return false
    if (!q) return true
    return `${e.message ?? ''} ${e.ipo_id ?? ''}`.toLowerCase().includes(q)
  })
}

export interface ConsoleRow {
  entry: LogEntry
  count: number // 1 normally; N when a run of identical events was folded (e.g. fetch_retry ×47)
  key: string
}

// The FULL payload identity of an entry, EXCLUDING `seq` (ring-only — a disk twin of the same line
// carries no seq, so including it would make a line and its disk twin look different and defeat the
// seam de-dup). Keys are sorted so a ring payload and its disk twin (parsed back from JSON) serialize
// identically. This is BOTH the seam de-dup identity (prependOlder) AND the base for a disk row's
// React key — so two genuinely-distinct same-millisecond events (they differ in some extra) are
// neither merged at the seam nor collapsed onto one key.
function identity(e: LogEntry): string {
  const ordered: Record<string, unknown> = {}
  for (const k of Object.keys(e).sort()) if (k !== 'seq') ordered[k] = e[k]
  return JSON.stringify(ordered)
}

// The base React key for a collapsed row, namespaced by source so a ring `seq` can NEVER collide with
// a disk row — the F8c/d bug was `${seq ?? rows.length}`, which let a disk array-index equal a ring
// seq (and shifted every prepend). Ring rows key off their intrinsic monotonic `seq`; disk rows (no
// seq) off their full identity.
function rowKeyBase(e: LogEntry): string {
  return e.seq != null ? `r:${e.seq}` : `d:${identity(e)}`
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
      last.entry = entry // keep the latest detail — and the run's key anchor (see below)
    } else {
      rows.push({ entry, count: 1, key: '' })
    }
  }
  // Assign keys AFTER the runs are complete, anchored on each run's NEWEST entry (`row.entry`).
  // Anchoring on the newest (not the first) keeps a row's key STABLE when an older page prepends and
  // merges into the run's front: only `count` grows, the key doesn't, so React never remounts it. The
  // Set makes the keys provably unique even in the (astronomically rare) two-identical-disk-payloads
  // case; the suffix is a defensive net, never the routine path (distinct events → distinct identity).
  const used = new Set<string>()
  for (const row of rows) {
    const base = rowKeyBase(row.entry)
    let key = base
    for (let n = 2; used.has(key); n++) key = `${base}#${n}`
    used.add(key)
    row.key = key
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

// The ring's `seq` is per-process. An engine restart resets it to 1, so a client still polling at the
// old high `since` gets zero rows forever — a SILENT freeze (no error, no cue), recoverable today only
// by closing and reopening the console. When the reported `last_seq` is strictly BELOW our cursor the
// ring has regressed → the engine restarted → the caller resets `since` to 0 and re-pulls the fresh
// tail. Strict `<`: equal is the steady state (no new lines this poll), and after a reset the cursor
// re-syncs to the live ring's monotonic `last_seq`, so the very next poll has `last_seq >= since` and
// can never re-trigger — at most one reset per actual restart, so it cannot loop/thrash.
export function shouldResetCursor(lastSeq: number, since: number): boolean {
  return lastSeq < since
}

// The `&level=` query fragment for a chip selection ('all' → none; the server reads warn/err as
// min-level). Kept here so the fetch sites and the tests share one source of truth.
export function levelParam(level: 'all' | LevelClass): string {
  return level === 'all' ? '' : `&level=${level}`
}

// F8b: a level is now a FETCH dimension — changing it RE-PULLS the tail at the new min-level (server-
// filtered across the whole ring), back-filled from a disk page when the ring is thin. This pure
// helper computes EXACTLY the state that resets on that re-pull. Everything NOT returned here is
// deliberately left untouched: `query` (the orthogonal text filter), `restoreRef` (prepend-only), and
// `openKey` (an expanded row stays open if it survives the new filter, else dangles harmlessly).
export interface LevelPull {
  entries: LogEntry[]
  since: number // → sinceRef (the ring's global last_seq)
  oldestTs: string | null // → oldestTsRef (the scroll-back cursor)
  historyDone: boolean // → historyDoneRef (false: a new level has its own history to page)
  pinned: boolean // → pinnedRef (true: re-open stuck to the bottom)
}
export function resetForLevel(
  tail: { entries: LogEntry[]; last_seq: number },
  backfill: LogEntry[] | null,
): LevelPull {
  const entries =
    backfill && backfill.length > 0 ? prependOlder(backfill, tail.entries) : tail.entries
  return {
    entries,
    since: tail.last_seq,
    oldestTs: entries[0]?.ts ?? null,
    historyDone: false,
    pinned: true,
  }
}

// Scroll-back stitch: prepend an older disk page ahead of the current buffer, dropping any entry
// already shown (the boundary line overlaps because the `before` cursor is inclusive). De-dup is by
// full `identity` (ts+logger+message+ipo_id + every extra, seq excluded) — NOT just
// ts+logger+message+ipo_id, which merged two genuinely-distinct same-millisecond events and dropped
// one (silent loss). Now only exact-payload twins (the same line seen on both ring and disk) collapse;
// distinct events are both kept. So the one continuous timeline has NO duplicate and NO gap at the
// seam. Returns the same array reference when nothing new is older (lets the caller detect
// "history exhausted").
export function prependOlder(older: LogEntry[], current: LogEntry[]): LogEntry[] {
  if (older.length === 0) return current
  const seen = new Set(current.map(identity))
  const fresh = older.filter((e) => !seen.has(identity(e)))
  return fresh.length === 0 ? current : fresh.concat(current)
}
