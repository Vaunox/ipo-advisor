import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useBoard } from '../api/hooks'
import type { IPOListRow } from '../api/types'
import { Loading } from '../components/Loading'
import { getPinned, hasChanged, seedLastSeen, togglePinned, useLastSeen } from '../state/prefs'
import { midnight, statusLabel, today } from '../status'
import { toast } from '../toast'
import { VMETA } from '../verdict'

const STAR = (
  <svg viewBox="0 0 24 24">
    <path d="M12 2l3 6.5 7 .6-5.3 4.7L18.5 21 12 17.3 5.5 21l1.8-7.2L2 9.1l7-.6z" />
  </svg>
)

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

// Self-contained ticking countdown so only THIS node re-renders each second — the row list never
// re-renders on the timer, which keeps scrolling smooth (a list-wide re-render mid-scroll was what
// made the FLIP animation misfire and "snap").
function Countdown() {
  const [, setNow] = useState(0)
  useEffect(() => {
    const id = window.setInterval(() => setNow((n) => n + 1), 1000)
    return () => window.clearInterval(id)
  }, [])
  return <span className="cd">{closeCountdown()}</span>
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
  const { data, isLoading, isError, refetch } = useBoard()
  const [sort, setSort] = useState<{ key: SortKey; dir: number }>({ key: 'verdict', dir: 1 })
  const [pinned, setPinned] = useState<Set<string>>(getPinned)
  const [attnDismissed, setAttnDismissed] = useState(false)

  // Review #8: reactive read so the CHANGED badge actually drops when a baseline advances on
  // Detail-open (BUG-3 pattern — a plain snapshot would go stale), not the old frozen `getLastSeen()`.
  const lastSeen = useLastSeen()
  const ordered = useMemo(() => {
    if (!data) return []
    // Live signals = currently bidding: opened, not yet closed, not yet listed. Retires on
    // close_date (the same book_closed anchor build_features uses, features/build.py) — the day
    // AFTER close it leaves Live, at the exact boundary History's "Awaiting listing outcome"
    // picks it up (close_date < today), so a closed IPO hands off with no gap and no double-show.
    // It stays through the close day itself (matching statusLabel's "CLOSES TODAY", still live).
    // Already-listed IPOs belong to History; not-yet-open ones to Upcoming.
    const t = today()
    const active = data.filter(
      (r) => r.listing_date == null && midnight(r.open_date) <= t && midnight(r.close_date) >= t,
    )
    const val = (r: IPOListRow): string | number => {
      if (sort.key === 'company') return r.name.toLowerCase()
      if (sort.key === 'verdict') return VMETA[r.verdict].rank
      return r.probability ?? -1
    }
    return active.sort((a, b) => {
      const pa = pinned.has(a.ipo_id) ? 0 : 1
      const pb = pinned.has(b.ipo_id) ? 0 : 1
      if (pa !== pb) return pa - pb
      const x = val(a),
        y = val(b)
      return x < y ? -sort.dir : x > y ? sort.dir : 0
    })
  }, [data, sort, pinned])

  // Review #8: give each LIVE row a baseline the first time it appears here — silently, so a new row
  // is never "changed" — and incrementally per-IPO (kills the old write-once snapshot). Scoped to the
  // Live rows (the badge is Live-only), never the whole board, so an upcoming/closed verdict can't
  // seed a baseline that later false-lights. `seedLastSeen` no-ops when nothing is missing.
  useEffect(() => {
    seedLastSeen(Object.fromEntries(ordered.map((r) => [r.ipo_id, r.verdict])))
  }, [ordered])

  // FLIP: animate rows to their new position when the ORDER changes (sort/pin). Keyed on the id
  // sequence so it only runs on a real reorder — never on scroll or the countdown tick. Measures
  // offsetTop (scroll-invariant), so scrolling can never be mistaken for a layout change.
  const els = useRef<Map<string, HTMLDivElement>>(new Map())
  const pos = useRef<Map<string, number>>(new Map())
  const firstFlip = useRef(true)
  const orderKey = ordered.map((r) => r.ipo_id).join('|')
  useLayoutEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    els.current.forEach((el, id) => {
      const top = el.offsetTop
      const prev = pos.current.get(id)
      if (!firstFlip.current && !reduce && prev != null && Math.abs(prev - top) > 1) {
        el.animate([{ transform: `translateY(${prev - top}px)` }, { transform: 'none' }], {
          duration: 360,
          easing: 'cubic-bezier(.22,1,.36,1)',
        })
      }
      pos.current.set(id, top)
    })
    firstFlip.current = false
  }, [orderKey])

  if (isLoading) return <Loading label="Loading verdicts…" />
  if (isError || !data)
    return (
      <div className="state">
        <h3>Couldn't load verdicts</h3>
        <p>The engine isn't responding. Check that it's running, then retry.</p>
        <button className="btn" onClick={() => void refetch()}>
          Retry
        </button>
      </div>
    )

  const onPin = (id: string) => {
    const s = togglePinned(id)
    setPinned(new Set(s))
    toast(s.has(id) ? 'Pinned to top' : 'Unpinned')
  }
  const toggleSort = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: key === 'prob' ? -1 : 1 }))
  const caret = (key: SortKey) => (sort.key === key ? (sort.dir > 0 ? '▲' : '▼') : '⇅')
  const cls = (key: SortKey) => (sort.key === key ? 'sorted' : '')

  const closing = data.filter((r) => statusLabel(r).closesToday)
  // Nearest not-yet-open IPO on the calendar (data already on the board) — powers the empty-state hint.
  const nextUp = data
    .filter((r) => r.listing_date == null && midnight(r.open_date) > today())
    .sort((a, b) => +midnight(a.open_date) - +midnight(b.open_date))[0]
  const fmtOpen = (iso: string) =>
    new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
    })

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
            — place bids before 17:00 IST · <Countdown /> left
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
      {ordered.length ? (
        <div className="rows">
          {ordered.map((row) => (
            <Row
              key={row.ipo_id}
              row={row}
              pinned={pinned.has(row.ipo_id)}
              changed={hasChanged(lastSeen, row.ipo_id, row.verdict)}
              onPin={onPin}
              onOpen={onOpen}
              setEl={(el) => {
                if (el) els.current.set(row.ipo_id, el)
                else els.current.delete(row.ipo_id)
              }}
            />
          ))}
        </div>
      ) : (
        <div className="state">
          <h3>No IPOs open right now</h3>
          {nextUp ? (
            <p>
              No mainboard book is currently open. <b>Next up — {nextUp.name}</b>, opens{' '}
              {fmtOpen(nextUp.open_date)}. See <b>Upcoming</b> for the full calendar, or{' '}
              <b>History</b> for past calls.
            </p>
          ) : (
            <p>
              No mainboard book is currently open, and none are on the calendar yet. Live verdicts
              appear here the moment an issue opens and its subscription lands. See <b>History</b>{' '}
              for past calls.
            </p>
          )}
        </div>
      )}
    </>
  )
}
