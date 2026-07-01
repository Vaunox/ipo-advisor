import { useState } from 'react'
import { useBoard } from '../api/hooks'
import type { IPOListRow } from '../api/types'

const midnight = (d: string) => new Date(d + 'T00:00:00')
const today = () => {
  const t = new Date()
  t.setHours(0, 0, 0, 0)
  return t
}

// Open or upcoming = not yet listed, and the book has not closed in the past.
function isUpcoming(row: IPOListRow): boolean {
  const listing = row.listing_date ? midnight(row.listing_date) : null
  if (listing && listing <= today()) return false
  return midnight(row.close_date) >= today()
}

function opensLabel(row: IPOListRow): { text: string; live: boolean } {
  const t = today()
  const open = midnight(row.open_date)
  const close = midnight(row.close_date)
  const day = 86_400_000
  if (open > t) return { text: `opens in ${Math.round((+open - +t) / day)}d`, live: false }
  if (close >= t) return { text: 'Open now', live: true }
  return { text: '—', live: false }
}

const sizeLabel = (cr: number | null): string =>
  cr != null ? `₹${cr.toLocaleString('en-IN')} cr` : '—'

function Bell() {
  const [on, setOn] = useState(false)
  return (
    <button
      className={on ? 'bell on' : 'bell'}
      title="Notify when this opens / gets a verdict"
      aria-pressed={on}
      onClick={() => setOn((v) => !v)}
    >
      <svg viewBox="0 0 24 24">
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" />
      </svg>
    </button>
  )
}

export function Upcoming() {
  const { data, isLoading, isError } = useBoard()
  if (isLoading) return <div className="state">Loading calendar…</div>
  if (isError || !data)
    return (
      <div className="state">
        <h3>Couldn't load the calendar</h3>
        <p>The engine isn't responding.</p>
      </div>
    )

  const rows = data.filter(isUpcoming)
  if (!rows.length)
    return (
      <div className="state">
        <h3>No open or upcoming IPOs</h3>
        <p>
          Nothing on the mainboard calendar right now. Open and upcoming issues appear here with
          their dates; verdicts land once the book closes.
        </p>
      </div>
    )

  return (
    <>
      <div className="lhead grid-up">
        <div>Company</div>
        <div>Opens</div>
        <div>Book window</div>
        <div className="r">Notify</div>
      </div>
      <div className="rows">
        {rows.map((row) => {
          const o = opensLabel(row)
          return (
            <div className="row grid-up" key={row.ipo_id} style={{ cursor: 'default' }}>
              <div className="co">
                <div className="name">{row.name}</div>
                <small>
                  {row.segment} · {sizeLabel(row.issue_size_cr)}
                </small>
              </div>
              <div>
                <div className="count-badge">{o.live ? 'OPEN NOW' : o.text}</div>
                <div className="pending-sm">book not closed — verdict pending</div>
              </div>
              <div className="pending-sm" style={{ color: 'var(--tx2)', marginTop: 0 }}>
                {row.open_date} → {row.close_date}
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <Bell />
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}
