import { useMemo, useState } from 'react'
import { useCalibration, useHistory } from '../api/hooks'
import type { CalibrationView, HistoryRow, VerdictType } from '../api/types'
import { getCosts } from '../state/prefs'
import { VMETA } from '../verdict'

const Search = () => (
  <svg viewBox="0 0 24 24">
    <circle cx="11" cy="11" r="7" />
    <path d="m21 21-4-4" />
  </svg>
)

const pctOf = (frac: number): number => Math.round(frac * 100)

function callMark(h: HistoryRow): { t: string; c: string } {
  if (h.verdict === 'APPLY')
    return h.listed_positive ? { t: '✓ HIT', c: 'hit' } : { t: '✗ MISS', c: 'miss' }
  if (h.verdict === 'SKIP')
    return !h.listed_positive ? { t: '✓ AVOIDED', c: 'hit' } : { t: '— missed pop', c: 'neutral' }
  return { t: '~ borderline', c: 'neutral' }
}
const callText = (h: HistoryRow) => callMark(h).t.replace(/[✓✗—~]\s*/g, '')

function Scorecard({ history, cal }: { history: HistoryRow[]; cal?: CalibrationView }) {
  const applies = history.filter((h) => h.verdict === 'APPLY')
  const applyPos = applies.filter((h) => h.listed_positive).length
  const applyRate = applies.length ? Math.round((applyPos / applies.length) * 100) : 0
  const avgPred = applies.length
    ? Math.round((applies.reduce((s, h) => s + (h.probability ?? 0) * 100, 0)) / applies.length)
    : 0
  const skips = history.filter((h) => h.verdict === 'SKIP')
  const skipAvoided = skips.filter((h) => !h.listed_positive).length
  return (
    <div className="scorecard">
      <div className="sc">
        <div className="lab">IPOs scored</div>
        <div className="val">{history.length}</div>
        <div className="note">with a listing outcome</div>
      </div>
      <div className="sc">
        <div className="lab">APPLY hit rate</div>
        <div className="val" style={{ color: 'var(--apply)' }}>
          {applyRate}%<small> actual</small>
        </div>
        <div className="note">
          {applyPos}/{applies.length} listed positive · predicted ~{avgPred}%
        </div>
        <div className="relbar">
          <div className="pred" style={{ left: `${avgPred}%` }} />
          <i style={{ width: `${applyRate}%` }} />
        </div>
      </div>
      <div className="sc">
        <div className="lab">SKIPs avoided</div>
        <div className="val">
          {skipAvoided}/{skips.length}
        </div>
        <div className="note">flagged issues that fell on listing</div>
      </div>
      <div className="sc">
        <div className="lab">Calibration</div>
        <div className="val" style={{ fontSize: 19 }}>
          {cal?.gate_passed ? 'Tracking' : 'Un-gated'}
        </div>
        <div className="note">{cal?.ece != null ? `ECE ${cal.ece.toFixed(3)} · held-out` : '—'}</div>
      </div>
    </div>
  )
}

function ReliabilityDiagram({ cal }: { cal: CalibrationView }) {
  if (!cal.bins.length)
    return (
      <div className="reldiag">
        <h3 className="sec" style={{ margin: 0 }}>
          Reliability — predicted vs actual
        </h3>
        <div className="pending" style={{ marginTop: 8 }}>
          {cal.source === 'report not generated'
            ? 'No held-out reliability report yet — run scripts/run_reliability_export.py.'
            : 'No reliability bins available.'}
        </div>
      </div>
    )
  const S = 250,
    P = 34
  const X = (f: number) => P + f * S
  const Y = (f: number) => P + S - f * S
  const W = P + S + 18,
    H = P + S + 34
  const line = cal.bins.map((b) => `${X(b.mean_predicted).toFixed(1)},${Y(b.observed_rate).toFixed(1)}`).join(' ')
  const band = `M ${X(0)} ${Y(0.12)} L ${X(0.88)} ${Y(1)} L ${X(1)} ${Y(1)} L ${X(1)} ${Y(0.88)} L ${X(0.12)} ${Y(0)} L ${X(0)} ${Y(0)} Z`
  const ticks = [0, 0.5, 1]
  const maxN = Math.max(...cal.bins.map((b) => b.count), 1)
  return (
    <div className="reldiag">
      <div className="rd-head">
        <h3 className="sec" style={{ margin: 0 }}>
          Reliability — predicted vs actual
        </h3>
        <div className="sub">
          {cal.n} scored IPOs · {cal.source} · does a "~70%" verdict really list positive ~70% of the time?
        </div>
      </div>
      <div className="rd-body">
        <svg className="rd-svg" viewBox={`0 0 ${W} ${H}`} width={W} height={H}>
          <path className="rd-band" d={band} />
          <line className="rd-diag" x1={X(0)} y1={Y(0)} x2={X(1)} y2={Y(1)} />
          <line className="rd-axis" x1={P} y1={P} x2={P} y2={P + S} />
          <line className="rd-axis" x1={P} y1={P + S} x2={P + S} y2={P + S} />
          <polyline className="rd-line" points={line} />
          {cal.bins.map((b, i) => (
            <circle
              key={i}
              className="rd-pt"
              cx={X(b.mean_predicted)}
              cy={Y(b.observed_rate)}
              r={3.5 + (b.count / maxN) * 6}
            />
          ))}
          {ticks.map((t) => (
            <text key={`x${t}`} className="rd-tick" x={X(t)} y={P + S + 13} textAnchor="middle">
              {Math.round(t * 100)}
            </text>
          ))}
          {ticks.map((t) => (
            <text key={`y${t}`} className="rd-tick" x={P - 8} y={Y(t) + 3} textAnchor="end">
              {Math.round(t * 100)}
            </text>
          ))}
          <text className="rd-axlabel" x={P + S / 2} y={P + S + 28} textAnchor="middle">
            predicted probability %
          </text>
        </svg>
        <div className="rd-right">
          <div className="rd-caption">
            <b>Points hug the diagonal.</b> When the model says ~70%, those IPOs listed positive about
            70% of the time — the probability means what it says. This is the held-out (walk-forward)
            calibration, not an in-sample recompute.
          </div>
          <div className="rd-buckets">
            {cal.bins.map((b, i) => (
              <div className="rd-brow" key={i}>
                <span className="bp">{pctOf(b.mean_predicted)}% pred</span>
                <span className="bar">
                  <i style={{ width: `${pctOf(b.observed_rate)}%` }} />
                </span>
                <span className="ba">
                  <b>{pctOf(b.observed_rate)}%</b> obs <span className="n">· n{b.count}</span>
                </span>
              </div>
            ))}
          </div>
          <div className="rd-legend">
            <span className="k">
              <i /> perfect calibration
            </span>
            <span className="k">
              <span className="dotk" /> observed bucket · size = n
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

type SortKey = 'company' | 'verdict' | 'prob' | 'actual' | 'date'

function csvCell(v: string): string {
  return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v
}

export function History() {
  const { data: history, isLoading, isError } = useHistory(getCosts())
  const cal = useCalibration()
  const [filter, setFilter] = useState<'all' | VerdictType>('all')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<{ key: SortKey; dir: number }>({ key: 'date', dir: -1 })

  const rows = useMemo(() => {
    if (!history) return []
    const q = query.toLowerCase()
    let r = history.filter(
      (h) => (filter === 'all' || h.verdict === filter) && h.name.toLowerCase().includes(q),
    )
    const val = (h: HistoryRow): string | number => {
      switch (sort.key) {
        case 'company':
          return h.name.toLowerCase()
        case 'verdict':
          return VMETA[h.verdict].rank
        case 'prob':
          return h.probability ?? -1
        case 'actual':
          return h.net_return
        default:
          return h.listing_date ?? ''
      }
    }
    r = [...r].sort((a, b) => {
      const x = val(a),
        y = val(b)
      return x < y ? -sort.dir : x > y ? sort.dir : 0
    })
    return r
  }, [history, filter, query, sort])

  if (isLoading) return <div className="state">Loading history…</div>
  if (isError || !history)
    return (
      <div className="state">
        <h3>Couldn't load history</h3>
        <p>The engine isn't responding.</p>
      </div>
    )

  const toggleSort = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: key === 'company' ? 1 : -1 }))
  const caret = (key: SortKey) => (sort.key === key ? (sort.dir > 0 ? '▲' : '▼') : '⇅')

  const exportCSV = () => {
    const head = ['Company', 'ListingDate', 'Verdict', 'Predicted', 'ActualNet', 'Call']
    const lines = [head.join(',')].concat(
      rows.map((h) =>
        [
          h.name,
          h.listing_date ?? '',
          h.verdict,
          h.probability != null ? `${pctOf(h.probability)}%` : '',
          `${(h.net_return * 100).toFixed(1)}%`,
          callText(h),
        ]
          .map(csvCell)
          .join(','),
      ),
    )
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'ipo-history.csv'
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const chips: ('all' | VerdictType)[] = ['all', 'APPLY', 'MARGINAL', 'SKIP']

  return (
    <>
      <Scorecard history={history} cal={cal.data} />
      {cal.data && <ReliabilityDiagram cal={cal.data} />}
      <div className="hist-tools">
        <div className="hist-search">
          <Search />
          <input
            placeholder="Search history…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="chips">
          {chips.map((c) => (
            <button
              key={c}
              className={filter === c ? 'chip on' : 'chip'}
              onClick={() => setFilter(c)}
            >
              {c === 'all' ? 'All' : c}
            </button>
          ))}
        </div>
        <span className="spacer" />
        <button className="btn" onClick={exportCSV}>
          Export CSV
        </button>
      </div>
      <div className="lhead grid-hist">
        <div data-sort="company" className={sort.key === 'company' ? 'sorted' : ''} onClick={() => toggleSort('company')}>
          Company<span className="caret">{caret('company')}</span>
        </div>
        <div data-sort="verdict" className={sort.key === 'verdict' ? 'sorted' : ''} onClick={() => toggleSort('verdict')}>
          Verdict<span className="caret">{caret('verdict')}</span>
        </div>
        <div data-sort="prob" className={sort.key === 'prob' ? 'sorted' : ''} onClick={() => toggleSort('prob')}>
          Predicted<span className="caret">{caret('prob')}</span>
        </div>
        <div data-sort="actual" className={sort.key === 'actual' ? 'sorted' : ''} onClick={() => toggleSort('actual')}>
          Actual (net)<span className="caret">{caret('actual')}</span>
        </div>
        <div className="r">Call</div>
      </div>
      {rows.length ? (
        <div className="rows">
          {rows.map((h) => {
            const m = VMETA[h.verdict]
            const cm = callMark(h)
            const pos = h.net_return > 0
            return (
              <div className="row grid-hist" key={h.ipo_id} style={{ cursor: 'default' }}>
                <div className="co">
                  <div className="name">{h.name}</div>
                  <small>{h.listing_date ?? '—'}</small>
                </div>
                <div>
                  <span className={`tag t-${m.cls}`}>{m.label}</span>
                </div>
                <div>
                  {h.probability != null ? (
                    <span className="mono">{pctOf(h.probability)}%</span>
                  ) : (
                    <span className="pending">n/a</span>
                  )}
                </div>
                <div className={`actual ${pos ? 'pos' : 'neg'}`}>
                  {pos ? '+' : ''}
                  {(h.net_return * 100).toFixed(1)}%
                </div>
                <div style={{ textAlign: 'right' }}>
                  <span className={`hitmark ${cm.c}`}>{cm.t}</span>
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="state">
          <h3>No matching IPOs</h3>
          <p>Nothing matches this filter and search.</p>
        </div>
      )}
    </>
  )
}
