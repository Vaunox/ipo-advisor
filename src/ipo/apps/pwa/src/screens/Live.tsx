import { useBoard } from '../api/hooks'
import type { IPOListRow } from '../api/types'
import { VMETA } from '../verdict'

function statusLabel(row: IPOListRow): { text: string; live: boolean } {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const open = new Date(row.open_date + 'T00:00:00')
  const close = new Date(row.close_date + 'T00:00:00')
  const listing = row.listing_date ? new Date(row.listing_date + 'T00:00:00') : null
  if (listing && listing <= today) return { text: 'Listed', live: false }
  if (close < today) return { text: 'Closed', live: false }
  if (open <= today) return { text: 'Open', live: true }
  return { text: 'Upcoming', live: false }
}

const sizeLabel = (cr: number | null): string =>
  cr != null ? `₹${cr.toLocaleString('en-IN')} cr` : '—'

function Row({ row, onOpen }: { row: IPOListRow; onOpen: (id: string) => void }) {
  const m = VMETA[row.verdict]
  const isKill = row.kill_flags.length > 0
  // A kill-flag forces SKIP regardless of the score, so lead with the override, not a number
  // (matches the locked design). The engine's probability is still there; the UI just doesn't
  // headline it for a forced SKIP.
  const showNumber = row.probability != null && !isKill
  const pct = row.probability != null ? Math.round(row.probability * 100) : null
  const st = statusLabel(row)
  return (
    <div
      className="row grid-live"
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
        <div className="name">{row.name}</div>
        <small>
          {row.segment} · {sizeLabel(row.issue_size_cr)} ·{' '}
          {st.live ? <b>{st.text.toUpperCase()}</b> : st.text}
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
  if (isLoading) return <div className="state">Loading verdicts…</div>
  if (isError || !data)
    return (
      <div className="state">
        <h3>Couldn't load verdicts</h3>
        <p>The engine isn't responding. Check that it's running, then retry.</p>
      </div>
    )
  return (
    <>
      <div className="lhead grid-live">
        <div>Company</div>
        <div>Verdict</div>
        <div>Prob.</div>
        <div>Grounded reason</div>
      </div>
      <div className="rows">
        {data.map((row) => (
          <Row key={row.ipo_id} row={row} onOpen={onOpen} />
        ))}
      </div>
    </>
  )
}
