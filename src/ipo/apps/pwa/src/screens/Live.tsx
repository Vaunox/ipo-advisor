import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useBoard } from '../api/hooks'
import type { IPOListRow } from '../api/types'
import { getLastSeen, getPinned, seedLastSeen, togglePinned } from '../state/prefs'
import { VMETA } from '../verdict'

const STAR = (
  <svg viewBox="0 0 24 24">
    <path d="M12 2l3 6.5 7 .6-5.3 4.7L18.5 21 12 17.3 5.5 21l1.8-7.2L2 9.1l7-.6z" />
  </svg>
)

const midnight = (d: string) => new Date(d + 'T00:00:00')
const today = () => {
  const t = new Date()
  t.setHours(0, 0, 0, 0)
  return t
}

function statusLabel(row: IPOListRow): { text: string; live: boolean; closesToday: boolean } {
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

const sizeLabel = (cr: number | null): string => (cr != null ? `₹${cr.toLocaleString('en-IN')} cr` : '—')

// Time remaining until the 17:00 IST subscription close, formatted.
function closeCountdown(): string {
  const istNow = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
  const t = new Date(istNow)
  t.setHours(17, 0, 0, 0)
  if (t <= istNow) t.setDate(t.getDate() + 1)
  let s = Math.floor((+t - +istNow) / 1000)
  const h = Math.floor(s / 3600)
  s %= 3600
  const m = Math.floor(s / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m ${s % 60}s`
}

type SortKey = 'company' | 'verdict' | 'prob'

function Row({
  row,
  pinned,
  changed,
  onPin,
  onOpen,
  setEl,
}: {
  row: IPOListRow
  pinned: boolean
  changed: boolean
  onPin: (id: string) => void
  onOpen: (id: string) => void
  setEl: (el: HTMLDivElement | null) => void
}) {
  const m = VMETA[row.verdict]
  const isKill = row.kill_flags.length > 0
  const showNumber = row.probability != null && !isKill
  const pct = row.probability != null ? Math.round(row.probability * 100) : null
  const st = statusLabel(row)
  return (
    <div
      className="row grid-live"
      ref={setEl}
      tabIndex={0}
      role="button"
      aria-label={`${row.name} — ${row.verdict}, open verdict detail`}
      onClick={() => onOpen(row.ipo_id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpen(row.ipo_id)
        }
      }}
    >
      <div className="spine" style={{ background: `var(--${m.cls})` }} />
      <div className="co">
        <div className="name">
          <button
            className={pinned ? 'star on' : 'star'}
            title="Pin to top"
            aria-pressed={pinned}
            onClick={(e) => {
              e.stopPropagation()
              onPin(row.ipo_id)
            }}
          >
            {STAR}
          </button>
          {row.name}
          {changed && <span className="changed" title="Verdict changed since you last looked">CHANGED</span>}
        </div>
        <small>
          {row.segment} · {sizeLabel(row.issue_size_cr)} · {st.live ? <b>{st.text}</b> : st.text}
        </small>
      </div>
      <div>
        <span className={`tag t-${m.cls}`}>{m.label}</span>
      </div>
      {showNumber ? (
        <div className="prob">
          {pct}%<small>calibrated</small>
        </div>
      ) : (
        <div className="prob none">
          — <small style={{ display: 'inline' }}>{isKill ? 'kill-flag' : 'no number'}</small>
        </div>
      )}
      <div className="reason">
        {row.reason}
        <div className="meter">
          <i
            style={{
              width: showNumber ? `${pct}%` : isKill ? '100%' : '0%',
              background: showNumber ? `var(--${m.cls})` : 'var(--skip)',
              opacity: showNumber ? 1 : isKill ? 0.4 : 0,
            }}
          />
        </div>
      </div>
    </div>
  )
}

export function Live({ onOpen }: { onOpen: (id: string) => void }) {
  const { data, isLoading, isError } = useBoard()
  const [sort, setSort] = useState<{ key: SortKey; dir: number }>({ key: 'verdict', dir: 1 })
  const [pinned, setPinned] = useState<Set<string>>(getPinned)
  const [attnDismissed, setAttnDismissed] = useState(false)
  const [, tick] = useState(0)

  // seed last-seen verdicts once, so the CHANGED badge lights up on a *real* future change
  useEffect(() => {
    if (data) seedLastSeen(Object.fromEntries(data.map((r) => [r.ipo_id, r.verdict])))
  }, [data])

  // re-tick the close countdown every second
  useEffect(() => {
    const id = window.setInterval(() => tick((n) => n + 1), 1000)
    return () => window.clearInterval(id)
  }, [])

  const lastSeen = getLastSeen()
  const ordered = useMemo(() => {
    if (!data) return []
    const val = (r: IPOListRow): string | number => {
      if (sort.key === 'company') return r.name.toLowerCase()
      if (sort.key === 'verdict') return VMETA[r.verdict].rank
      return r.probability ?? -1
    }
    return [...data].sort((a, b) => {
      const pa = pinned.has(a.ipo_id) ? 0 : 1
      const pb = pinned.has(b.ipo_id) ? 0 : 1
      if (pa !== pb) return pa - pb
      const x = val(a),
        y = val(b)
      return x < y ? -sort.dir : x > y ? sort.dir : 0
    })
  }, [data, sort, pinned])

  // FLIP: animate rows from their previous position to the new one on any reorder
  const els = useRef<Map<string, HTMLDivElement>>(new Map())
  const pos = useRef<Map<string, number>>(new Map())
  useLayoutEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    els.current.forEach((el, id) => {
      const top = el.getBoundingClientRect().top
      const prev = pos.current.get(id)
      if (prev != null && Math.abs(prev - top) > 1) {
        el.animate([{ transform: `translateY(${prev - top}px)` }, { transform: 'none' }], {
          duration: 360,
          easing: 'cubic-bezier(.22,1,.36,1)',
        })
      }
      pos.current.set(id, top)
    })
  })

  if (isLoading) return <div className="state">Loading verdicts…</div>
  if (isError || !data)
    return (
      <div className="state">
        <h3>Couldn't load verdicts</h3>
        <p>The engine isn't responding. Check that it's running, then retry.</p>
      </div>
    )

  const onPin = (id: string) => setPinned(new Set(togglePinned(id)))
  const toggleSort = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: key === 'prob' ? -1 : 1 }))
  const caret = (key: SortKey) => (sort.key === key ? (sort.dir > 0 ? '▲' : '▼') : '⇅')
  const cls = (key: SortKey) => (sort.key === key ? 'sorted' : '')

  const closing = data.filter((r) => statusLabel(r).closesToday)

  return (
    <>
      {closing.length > 0 && !attnDismissed && (
        <div className="attention">
          <svg viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 7v5l3 2" />
          </svg>
          <span>
            <b>
              {closing.length} IPO{closing.length > 1 ? 's' : ''} close today
            </b>{' '}
            — place bids before 17:00 IST · <span className="cd">{closeCountdown()}</span> left
          </span>
          <button className="att-x" onClick={() => setAttnDismissed(true)} title="Dismiss">
            ✕
          </button>
        </div>
      )}
      <div className="lhead grid-live">
        <div data-sort="company" className={cls('company')} onClick={() => toggleSort('company')}>
          Company<span className="caret">{caret('company')}</span>
        </div>
        <div data-sort="verdict" className={cls('verdict')} onClick={() => toggleSort('verdict')}>
          Verdict<span className="caret">{caret('verdict')}</span>
        </div>
        <div data-sort="prob" className={cls('prob')} onClick={() => toggleSort('prob')}>
          Prob.<span className="caret">{caret('prob')}</span>
        </div>
        <div>Grounded reason</div>
      </div>
      <div className="rows">
        {ordered.map((row) => (
          <Row
            key={row.ipo_id}
            row={row}
            pinned={pinned.has(row.ipo_id)}
            changed={!!lastSeen[row.ipo_id] && lastSeen[row.ipo_id] !== row.verdict}
            onPin={onPin}
            onOpen={onOpen}
            setEl={(el) => {
              if (el) els.current.set(row.ipo_id, el)
              else els.current.delete(row.ipo_id)
            }}
          />
        ))}
      </div>
    </>
  )
}
