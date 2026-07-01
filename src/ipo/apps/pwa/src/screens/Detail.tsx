import { useState } from 'react'
import { useIpo } from '../api/hooks'
import type { IPODetail, IPOFeatures, VerdictType } from '../api/types'
import { IconAlert } from '../components/Icons'
import { VMETA } from '../verdict'

const Check = () => (
  <svg viewBox="0 0 24 24">
    <path d="M20 6 9 17l-5-5" />
  </svg>
)

const x = (v: number | null): string => (v != null ? `${v}×` : '—')

// Readable label for each contribution key, enriched with the feature value where available.
function contribLabel(key: string, f: IPOFeatures): string {
  switch (key) {
    case 'qib_sub':
      return f.qib_sub != null ? `QIB ${f.qib_sub}×` : 'QIB'
    case 'nii_sub':
      return f.nii_sub != null ? `NII ${f.nii_sub}×` : 'NII'
    case 'retail_sub':
      return f.retail_sub != null ? `Retail ${f.retail_sub}×` : 'Retail'
    case 'anchor_quality':
      return f.anchor_quality != null ? `Anchors ${Math.round(f.anchor_quality * 100)}%` : 'Anchors'
    case 'relative_valuation':
      return f.relative_valuation != null ? `Valuation ${f.relative_valuation.toFixed(2)}×` : 'Valuation'
    case 'ofs_fraction':
      return f.ofs_fraction != null ? `OFS ${Math.round(f.ofs_fraction * 100)}%` : 'OFS'
    case 'market_regime':
      return f.market_regime != null
        ? `Regime ${f.market_regime > 0 ? '+' : ''}${f.market_regime.toFixed(1)}`
        : 'Regime'
    default:
      return key
  }
}

function whatIf(verdict: VerdictType, isKill: boolean): string {
  if (verdict === 'APPLY')
    return 'Holds as APPLY while the QIB book stays strong and no kill-flag fires. Softens to MARGINAL if institutional demand faded or the valuation re-rated rich.'
  if (verdict === 'MARGINAL')
    return 'Reaches APPLY if the QIB book firms with steady anchors. Slips to SKIP if a kill-flag (heavy OFS, promoter litigation) appears.'
  if (isKill)
    return 'The kill-flag override stands as long as the OFS share and litigation flags are active — subscription strength cannot lift it.'
  return 'A verdict lands once the book closes with QIB subscription and anchor allotment in hand. Until then the engine abstains.'
}

function Contributions({ d }: { d: IPODetail }) {
  const entries = Object.entries(d.contributions).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
  if (!entries.length)
    return <div className="pending">No contribution breakdown — verdict set by override / abstention.</div>
  const maxAbs = Math.max(...entries.map(([, v]) => Math.abs(v)), 1e-9)
  return (
    <div className="contrib">
      {entries.map(([key, v]) => {
        const pos = v >= 0
        const width = Math.min((Math.abs(v) / maxAbs) * 50, 50)
        return (
          <div className="c" key={key}>
            <div className="lab">{contribLabel(key, d.features)}</div>
            <div className="track">
              <div className="mid" />
              <b className={pos ? 'p' : 'n'} style={{ width: `${width}%` }} />
            </div>
            <div className={`val ${pos ? 'p' : 'n'}`}>
              {pos ? '+' : '−'}
              {Math.abs(v).toFixed(2)}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function Detail({ id, onBack }: { id: string; onBack: () => void }) {
  const { data: d, isLoading, isError } = useIpo(id)
  const [copied, setCopied] = useState(false)

  if (isLoading) return <div className="state">Loading verdict…</div>
  if (isError || !d)
    return (
      <div className="state">
        <h3>Couldn't load this IPO</h3>
        <button className="btn" onClick={onBack}>
          Back
        </button>
      </div>
    )

  const { record: r, verdict: v, features: f } = d
  const m = VMETA[v.verdict]
  const isKill = v.kill_flags.length > 0
  const showNumber = v.probability != null && !isKill
  const pct = v.probability != null ? Math.round(v.probability * 100) : null
  const cold = v.watch.find((w) => /cold market/i.test(w))
  const watch = v.watch.filter((w) => !/cold market/i.test(w))
  const fresh = r.ofs_fraction != null ? `${Math.round((1 - r.ofs_fraction) * 100)} / ${Math.round(r.ofs_fraction * 100)}` : '—'
  const band = `₹${r.price_band_low}–${r.price_band_high}`

  const copy = () => {
    const txt = `${r.name} — ${v.verdict}${showNumber ? ` (${pct}% calibrated)` : ''}. ${v.reason}. Advisory only, not financial advice.`
    void navigator.clipboard?.writeText(txt)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1600)
  }

  return (
    <>
      <a className="back" onClick={onBack}>
        <svg viewBox="0 0 24 24">
          <path d="M15 18l-6-6 6-6" />
        </svg>{' '}
        Back to live signals
      </a>
      <div className="det">
        <div className="card det-hero">
          <div className={`verdict-badge t-${m.cls}`}>
            {v.verdict === 'INSUFFICIENT_SIGNAL' ? 'INSUFF.' : v.verdict}
          </div>
          <div className="hero-meta">
            <h2>{r.name}</h2>
            <div className="m">
              {r.segment} · Issue {r.issue_size_cr != null ? `₹${r.issue_size_cr.toLocaleString('en-IN')} cr` : '—'} · Band {band}
            </div>
            {showNumber && (
              <div className="gate">
                <Check /> RELIABILITY GATE PASSED
              </div>
            )}
          </div>
          <div className="hero-prob">
            {showNumber ? (
              <div className="big mono">{pct}%</div>
            ) : (
              <div className="big none mono">—</div>
            )}
            <div className="lbl">
              {showNumber
                ? 'calibrated P(positive listing)'
                : isKill
                  ? 'verdict set by kill-flag override'
                  : 'engine abstained — no number'}
            </div>
          </div>
        </div>

        {showNumber && (
          <div className="card meterbar">
            <div className="mono" style={{ fontSize: 10.5, letterSpacing: '.13em', textTransform: 'uppercase', color: 'var(--tx3)', whiteSpace: 'nowrap' }}>
              Calibrated P(positive listing)
            </div>
            <div className="bigmeter">
              <i style={{ width: `${pct}%` }} />
            </div>
            <div className="mono" style={{ color: 'var(--tx3)', fontSize: 12, whiteSpace: 'nowrap' }}>
              {pct} / 100
            </div>
          </div>
        )}

        <div className="card">
          <h3 className="sec">Grounded reason</h3>
          <p className="reason-body">{v.reason}</p>
          <h3 className="sec" style={{ marginTop: 22 }}>
            What drove this
          </h3>
          <Contributions d={d} />
        </div>

        <div className="card">
          <h3 className="sec">Subscription (final)</h3>
          <div className="kv">
            <div className="r">
              <span className="k">QIB</span>
              <span className="v" style={{ color: 'var(--apply)' }}>{x(r.qib_sub)}</span>
            </div>
            <div className="r">
              <span className="k">NII</span>
              <span className="v">{x(r.nii_sub)}</span>
            </div>
            <div className="r">
              <span className="k">Retail</span>
              <span className="v">{x(r.retail_sub)}</span>
            </div>
          </div>
          <h3 className="sec" style={{ marginTop: 18 }}>
            Issue structure
          </h3>
          <div className="kv">
            <div className="r">
              <span className="k">Fresh / OFS</span>
              <span className="v">{fresh}</span>
            </div>
            <div className="r">
              <span className="k">Anchor quality</span>
              <span className="v" style={{ color: 'var(--apply)' }}>
                {f.anchor_quality != null ? f.anchor_quality.toFixed(2) : '—'}
              </span>
            </div>
            <div className="r">
              <span className="k">Lot</span>
              <span className="v">{r.lot_size != null ? `${r.lot_size} sh` : '—'}</span>
            </div>
          </div>
        </div>

        <div className="card">
          <h3 className="sec">Watch items</h3>
          {watch.length ? (
            <ul className="watch">
              {watch.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          ) : (
            <div className="pending">None.</div>
          )}
          <h3 className="sec" style={{ marginTop: 20 }}>
            Kill-flags
          </h3>
          {isKill ? (
            v.kill_flags.map((k, i) => (
              <div className="kf hit" key={i}>
                <IconAlert />
                {k}
              </div>
            ))
          ) : (
            <div className="kf ok">
              <Check /> None triggered
            </div>
          )}
        </div>

        <div className="whatif">
          <svg viewBox="0 0 24 24">
            <path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2zM9 21h6" />
          </svg>
          <span>
            <b>What would change this call:</b> {whatIf(v.verdict, isKill)}
          </span>
        </div>

        {cold && (
          <div className="caveat">
            <IconAlert />
            <span>
              <b>Cold market — probability less certain.</b> Annotation only; it does not change the
              number above.
            </span>
          </div>
        )}

        <div className="det-actions">
          <button className="btn" onClick={copy}>
            {copied ? 'Copied ✓' : 'Copy verdict as text'}
          </button>
          <span className="pending">Advisory only — there is no order control here, by design.</span>
        </div>

        <p className="foot-note">
          engineering/research reference — not financial advice · a calibrated probability is an
          estimate, not an assurance · advisory only — no orders, no recomputation
        </p>
      </div>
    </>
  )
}
