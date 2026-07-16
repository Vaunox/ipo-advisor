// Read-only debug console (v3 V3-16) — a terminal window over the app that shows the structured
// log the engine already writes. GET-only (a window, not a control panel); reading never triggers
// anything. Opened/closed by the ` key (enabled via Settings); Esc / ✕ / backdrop also close.
// Filterable by level + ipo_id/event; a failure loop collapses to one counted line. No live
// animation — a static read the operator refreshes or reopens.

import { useMemo, useState } from 'react'
import { useLogs } from '../api/hooks'
import {
  type LevelClass,
  collapse,
  filterEntries,
  formatDetail,
  levelClass,
  levelCode,
  shortTs,
} from '../state/logview'

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
  const logs = useLogs(true, { history, limit: 1000 })

  const rows = useMemo(
    () => collapse(filterEntries(logs.data?.entries ?? [], { level, query })),
    [logs.data, level, query],
  )

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
            title="recent = live ring buffer · history = durable rotated files (scroll back further)"
          >
            {history ? 'history' : 'recent'}
          </button>
          <button
            className="cl-icon"
            onClick={() => void logs.refetch()}
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

        <div className="cl-body">
          <div className="cl-head cl-grid">
            <span>ts</span>
            <span>level</span>
            <span>event</span>
            <span>ipo_id</span>
            <span>detail</span>
          </div>
          {logs.isError ? (
            <div className="cl-empty">log unavailable — the engine isn't responding</div>
          ) : rows.length === 0 ? (
            <div className="cl-empty">{logs.isLoading ? 'loading…' : 'no lines match the filter'}</div>
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
