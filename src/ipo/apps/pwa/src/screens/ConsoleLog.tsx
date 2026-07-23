// Read-only debug console (v3 V3-16) — a terminal window over the app showing the structured log
// the engine already writes. GET-only (a window, not a control panel); reading never triggers
// anything. Opened/closed by the ` key (enabled via Settings); Esc / ✕ / backdrop also close.
// Always dark (a dev tool — level colours tuned for a dark ground, not the app theme).
//
// ONE continuous timeline, no modes: it opens at the bottom auto-tailing the live ring (2.5s poll,
// appending new lines, stuck to newest); scroll up and it lazily loads older chunks — flowing from
// the in-memory ring into the durable disk files with no visible seam, stitched by timestamp with
// no duplicate and no gap (see prependOlder). Auto-follow pauses while you're scrolled up reading
// history and resumes when you scroll back to the bottom — standard `tail -f`. There is no "live"
// label and no ring/disk toggle: the user never needs to know which store a line came from.

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { apiGet } from '../api/client'
import type { LogEntry, LogsResponse } from '../api/types'
import {
  type LevelClass,
  appendCapped,
  collapse,
  filterEntries,
  formatDetail,
  levelClass,
  levelCode,
  prependOlder,
  shortTs,
} from '../state/logview'

const POLL_MS = 2500 // live-tail cadence — feels live on a local sidecar, doesn't hammer
const PAGE = 500 // older-history page size fetched per scroll-up
const LIVE_CAP = 4000 // trim the buffer front to this only while tailing at the bottom (constant mem)
const AT_BOTTOM_PX = 40 // "stuck to bottom" tolerance for the tail-follow pause/resume
const NEAR_TOP_PX = 140 // how close to the top triggers the next older-history page

const LEVELS: Array<'all' | LevelClass> = ['all', 'info', 'warn', 'err']
const LEVEL_LABEL: Record<'all' | LevelClass, string> = {
  all: 'all',
  info: 'info',
  warn: 'warn',
  err: 'error',
}

export function ConsoleLog({ onClose }: { onClose: () => void }) {
  const [level, setLevel] = useState<'all' | LevelClass>('all')
  const [query, setQuery] = useState('')
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [failed, setFailed] = useState(false)
  // F7: which row is expanded to its full detail. Bound to the row's STABLE key (r.key from the F8cd
  // fix), NOT an index — so an older page prepending doesn't move the expansion to a different row.
  const [openKey, setOpenKey] = useState<string | null>(null)

  const bodyRef = useRef<HTMLDivElement>(null)
  const sinceRef = useRef(0) // ring cursor for the live tail
  const oldestTsRef = useRef<string | null>(null) // oldest loaded ts — the scroll-back cursor
  const pinnedRef = useRef(true) // stuck to the bottom? starts true so we open on newest
  const loadingOlderRef = useRef(false) // guard against overlapping older-history fetches
  const historyDoneRef = useRef(false) // reached the start of the disk history
  const restoreRef = useRef<number | null>(null) // scrollHeight before a prepend, to hold position

  // Initial load: the recent ring tail. The timeline opens here, at the bottom.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const r = await apiGet<LogsResponse>('/logs?since=0&limit=1000')
        if (cancelled) return
        sinceRef.current = r.last_seq
        oldestTsRef.current = r.entries[0]?.ts ?? null
        setEntries(r.entries)
        setFailed(false)
      } catch {
        if (!cancelled) setFailed(true)
      }
    })()
    return () => void (cancelled = true)
  }, [])

  // Live tail: poll the ring `since` cursor and append new lines. Trim the front only while pinned
  // (don't yank away history the reader has scrolled back to).
  useEffect(() => {
    const id = window.setInterval(() => {
      void (async () => {
        try {
          const r = await apiGet<LogsResponse>(`/logs?since=${sinceRef.current}&limit=1000`)
          setFailed(false)
          if (r.entries.length > 0) {
            sinceRef.current = r.last_seq
            const cap = pinnedRef.current ? LIVE_CAP : Number.MAX_SAFE_INTEGER
            setEntries((prev) => appendCapped(prev, r.entries, cap))
          }
        } catch {
          setFailed(true) // keep last-known lines; a transient blip shouldn't blank the console
        }
      })()
    }, POLL_MS)
    return () => window.clearInterval(id)
  }, [])

  // Scroll-up → load the next older page from disk and stitch it on, seamlessly.
  const loadOlder = () => {
    if (loadingOlderRef.current || historyDoneRef.current || oldestTsRef.current == null) return
    loadingOlderRef.current = true
    void (async () => {
      try {
        const before = encodeURIComponent(oldestTsRef.current as string)
        const r = await apiGet<LogsResponse>(`/logs?history=true&before=${before}&limit=${PAGE}`)
        const el = bodyRef.current
        restoreRef.current = el ? el.scrollHeight : null // preserve the reader's position on prepend
        setEntries((prev) => {
          const merged = prependOlder(r.entries, prev)
          if (merged === prev) historyDoneRef.current = true // nothing older left — stop paging
          else oldestTsRef.current = merged[0]?.ts ?? oldestTsRef.current
          return merged
        })
      } catch {
        /* transient — leave the buffer as-is, a later scroll retries */
      } finally {
        loadingOlderRef.current = false
      }
    })()
  }

  const onScroll = () => {
    const el = bodyRef.current
    if (!el) return
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < AT_BOTTOM_PX
    if (el.scrollTop < NEAR_TOP_PX) loadOlder()
  }

  // Click a row to expand/collapse its detail. Guard on an active text selection so a drag-select
  // inside the row doesn't get swallowed as a toggle (a plain click clears the selection first, so it
  // still toggles; a drag leaves a selection, so it doesn't).
  const toggleRow = (key: string) => {
    if (window.getSelection()?.toString()) return
    setOpenKey((k) => (k === key ? null : key))
  }

  // Copy a full line. The .exe routes through the preload bridge (navigator.clipboard is unreliable in
  // a file:// renderer); a browser/dev has no bridge and uses the Clipboard API directly.
  const copyLine = (text: string) => {
    const bridge = (window as unknown as { ipoDesktop?: { copyText?: (t: string) => Promise<void> } })
      .ipoDesktop
    if (bridge?.copyText) void bridge.copyText(text)
    else void navigator.clipboard?.writeText(text)
  }

  const rows = useMemo(
    () => collapse(filterEntries(entries, { level, query })),
    [entries, level, query],
  )

  // After the rows change: hold the reader's position when we prepended older history, otherwise
  // stick to the bottom if they're tailing. (useLayoutEffect so the jump never flickers.)
  useLayoutEffect(() => {
    const el = bodyRef.current
    if (!el) return
    if (restoreRef.current != null) {
      el.scrollTop += el.scrollHeight - restoreRef.current // keep the same lines under the viewport
      restoreRef.current = null
    } else if (pinnedRef.current) {
      el.scrollTop = el.scrollHeight
    }
  }, [rows])

  return (
    <div
      className="cl-overlay"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      role="dialog"
      aria-label="Debug console log"
    >
      <div className="cl">
        <div className="cl-top">
          <span className="cl-title">CONSOLE LOG</span>
          <div className="cl-filters" role="group" aria-label="Filter by level">
            {LEVELS.map((lv) => (
              <button
                key={lv}
                className={`cl-chip ${lv}${level === lv ? ' on' : ''}`}
                aria-pressed={level === lv}
                onClick={() => setLevel(lv)}
              >
                {LEVEL_LABEL[lv]}
              </button>
            ))}
          </div>
          <div className="cl-search">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="ipo_id / event…"
              aria-label="Filter by ipo_id or event"
              spellCheck={false}
            />
          </div>
          <span className="cl-sp" />
          <span className="cl-ro">
            read-only <kbd>`</kbd>
          </span>
          <button className="cl-icon" onClick={onClose} title="Close" aria-label="Close console">
            ✕
          </button>
        </div>

        <div className="cl-body" ref={bodyRef} onScroll={onScroll}>
          <div className="cl-head cl-grid">
            <span>ts</span>
            <span>level</span>
            <span>event</span>
            <span>ipo_id</span>
            <span>detail</span>
          </div>
          {failed && rows.length === 0 ? (
            <div className="cl-empty">log unavailable — the engine isn't responding</div>
          ) : rows.length === 0 ? (
            <div className="cl-empty">no lines match the filter</div>
          ) : (
            rows.map((r) => (
              <div
                key={r.key}
                className={`cl-ln cl-grid ${levelClass(r.entry.level)}${openKey === r.key ? ' open' : ''}`}
                onClick={() => toggleRow(r.key)}
              >
                <span className="ts">{shortTs(r.entry.ts)}</span>
                <span className="lv">{levelCode(r.entry.level)}</span>
                <span className="ev">
                  {r.entry.message}
                  {r.count > 1 && <span className="xN"> ×{r.count}</span>}
                </span>
                <span className={`id${r.entry.ipo_id ? '' : ' none'}`}>{r.entry.ipo_id || '·'}</span>
                <span className="dt">{formatDetail(r.entry)}</span>
                {openKey === r.key && (
                  <button
                    className="cl-copy"
                    onClick={(e) => {
                      e.stopPropagation() // don't collapse the row we're copying from
                      copyLine(formatDetail(r.entry))
                    }}
                    title="Copy this line"
                  >
                    copy
                  </button>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
