// Read-only debug console (v3 V3-16) — a terminal window over the app that shows the structured
// log the engine already writes. GET-only (a window, not a control panel); reading never triggers
// anything. Opened/closed by the ` key (enabled via Settings); Esc / ✕ / backdrop also close.
// Filterable by level + ipo_id/event; a failure loop collapses to one counted line. Always dark
// (a dev tool — the level colours are calibrated for a dark ground, not the app theme).
//
// LIVE by behaviour, not by label: in the default (ring) mode it polls the `since` cursor every few
// seconds and APPENDS new lines — a `tail -f` you watch — auto-scrolling to newest while you're at
// the bottom, and pausing that follow the moment you scroll up to read history. The `history` toggle
// switches to a one-shot read of the durable rotated files (no polling — the past doesn't move).

import { useEffect, useMemo, useRef, useState } from 'react'
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
  shortTs,
} from '../state/logview'

const POLL_MS = 2500 // fast enough to feel live on a local sidecar, slow enough not to hammer
const MAX_ROWS = 3000 // client-side tail bound — keep the newest, drop the oldest (constant memory)
const AT_BOTTOM_PX = 40 // "stuck to bottom" tolerance for the tail-follow pause/resume

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
  const [history, setHistory] = useState(false)
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [failed, setFailed] = useState(false)
  const [tick, setTick] = useState(0) // manual-refresh trigger

  const sinceRef = useRef(0)
  const bodyRef = useRef<HTMLDivElement>(null)
  const pinnedRef = useRef(true) // stuck to bottom? starts true so we open on newest

  // Fetch loop. Live (ring) mode polls the `since` cursor and appends; history mode is a one-shot
  // read of the rotated files. Re-runs on a mode switch or a manual refresh (resets the cursor).
  useEffect(() => {
    let cancelled = false
    sinceRef.current = 0
    setEntries([])

    const pull = async () => {
      try {
        if (history) {
          const r = await apiGet<LogsResponse>('/logs?history=true&limit=1000')
          if (!cancelled) {
            setEntries(r.entries)
            setFailed(false)
          }
          return
        }
        const r = await apiGet<LogsResponse>(`/logs?since=${sinceRef.current}&limit=1000`)
        if (cancelled) return
        setFailed(false)
        if (r.entries.length > 0) {
          sinceRef.current = r.last_seq
          setEntries((prev) => appendCapped(prev, r.entries, MAX_ROWS))
        }
      } catch {
        if (!cancelled) setFailed(true) // keep last-known lines; a transient blip shouldn't blank it
      }
    }

    void pull()
    if (history) return () => void (cancelled = true) // the past doesn't move — no polling
    const id = window.setInterval(pull, POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [history, tick])

  const rows = useMemo(
    () => collapse(filterEntries(entries, { level, query })),
    [entries, level, query],
  )

  // tail-follow: after new rows render, stick to the bottom only if the reader is already there.
  useEffect(() => {
    const el = bodyRef.current
    if (el && pinnedRef.current) el.scrollTop = el.scrollHeight
  }, [rows])

  const onScroll = () => {
    const el = bodyRef.current
    if (el) pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < AT_BOTTOM_PX
  }

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
          <button
            className={`cl-toggle${history ? ' on' : ''}`}
            onClick={() => setHistory((h) => !h)}
            title="recent = live tail (auto-updates) · history = durable rotated files (scroll back further)"
          >
            {history ? 'history' : 'recent'}
          </button>
          <button
            className="cl-icon"
            onClick={() => setTick((t) => t + 1)}
            title="Refresh"
            aria-label="Refresh log"
          >
            ↻
          </button>
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
              <div key={r.key} className={`cl-ln cl-grid ${levelClass(r.entry.level)}`}>
                <span className="ts">{shortTs(r.entry.ts)}</span>
                <span className="lv">{levelCode(r.entry.level)}</span>
                <span className="ev">
                  {r.entry.message}
                  {r.count > 1 && <span className="xN"> ×{r.count}</span>}
                </span>
                <span className={`id${r.entry.ipo_id ? '' : ' none'}`}>{r.entry.ipo_id || '·'}</span>
                <span className="dt">{formatDetail(r.entry)}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
