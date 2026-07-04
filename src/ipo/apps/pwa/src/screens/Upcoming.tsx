import { useBoard } from '../api/hooks'
import type { IPOListRow } from '../api/types'
import { Loading } from '../components/Loading'

const midnight = (d: string) => new Date(d + 'T00:00:00')
const today = () => {
  const t = new Date()
  t.setHours(0, 0, 0, 0)
  return t
}
const DAY = 86_400_000

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
  if (open > t) return { text: `opens in ${Math.round((+open - +t) / DAY)}d`, live: false }
  if (close >= t) return { text: 'Open now', live: true }
  return { text: '—', live: false }
}

// Anchor allotment is disclosed ~1 trading day before the issue opens.
function anchorLabel(row: IPOListRow): { text: string; tomorrow: boolean } {
  const t = today()
  const anchor = new Date(+midnight(row.open_date) - DAY)
  const days = Math.round((+anchor - +t) / DAY)
  if (days === 1) return { text: 'TOMORROW ★', tomorrow: true }
  if (days > 1) return { text: `in ${days}d`, tomorrow: false }
  return { text: 'disclosed', tomorrow: false }
}

const sizeLabel = (cr: number | null): string =>
  cr != null ? `₹${cr.toLocaleString('en-IN')} cr` : '—'

function structureLabel(ofs: number | null): string {
  if (ofs == null) return '—'
  return `Fresh ${Math.round((1 - ofs) * 100)} / OFS ${Math.round(ofs * 100)}`
}

function valuationLabel(pe: number | null, peer: number | null): string {
  if (pe == null || peer == null) return '—'
  const gap = Math.round(((pe - peer) / peer) * 100)
  if (gap <= -5) return `${-gap}% below peers`
  if (gap >= 5) return `${gap}% above — rich`
  return 'in line with peers'
}

export function Upcoming({ onOpen }: { onOpen: (id: string) => void }) {
  const { data, isLoading, isError, refetch } = useBoard()
  if (isLoading) return <Loading label="Loading calendar…" />
  if (isError || !data)
    return (
      <div className="state">
        <h3>Couldn't load the calendar</h3>
        <p>The engine isn't responding.</p>
        <button className="btn" onClick={() => void refetch()}>
          Retry
        </button>
      </div>
    )

  const rows = data.filter(isUpcoming)
  if (!rows.length)
    return (
      <div className="state">
        <h3>No open or upcoming IPOs</h3>
        <p>
          Nothing on the mainboard calendar right now. Open and upcoming issues appear here with
          their dates, structure and valuation; verdicts land once the book closes.
        </p>
      </div>
    )

  return (
    <>
      <div className="lhead grid-up">
        <div>Company</div>
        <div>Opens</div>
        <div>Structure preview</div>
        <div>Valuation</div>
      </div>
      <div className="rows">
        {rows.map((row) => {
          const o = opensLabel(row)
          const a = anchorLabel(row)
          return (
            <div
              className="row grid-up"
              key={row.ipo_id}
              role="button"
              tabIndex={0}
              aria-label={`${row.name}, open detail`}
              onClick={() => onOpen(row.ipo_id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  onOpen(row.ipo_id)
                }
              }}
            >
              <div className="co">
                <div className="name">{row.name}</div>
                <small>
                  {row.segment} · {sizeLabel(row.issue_size_cr)}
                </small>
              </div>
              <div>
                <div className="count-badge">{o.live ? 'OPEN NOW' : o.text}</div>
                <div className="pending-sm">
                  anchor day: {a.tomorrow ? <span className="anchor-flag">{a.text}</span> : a.text}
                </div>
              </div>
              <div className="struct">{structureLabel(row.ofs_fraction)}</div>
              <div className="pending-sm" style={{ color: 'var(--tx2)', marginTop: 0 }}>
                {valuationLabel(row.issue_pe, row.peer_median_pe)}
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}
