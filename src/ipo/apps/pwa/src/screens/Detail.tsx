import { useState } from 'react'
import { useIpo, useIpoContext, useSubscriptionSeries, useTransitionsFor } from '../api/hooks'
import type { IPODetail, IPOFeatures, IpoContextView, VerdictType } from '../api/types'
import { IconAlert } from '../components/Icons'
import { Loading } from '../components/Loading'
import { SeriesChart } from '../components/SeriesChart'
import { chartState } from '../series'
import { isAllowedRhpUrl, openExternalUrl } from '../external'
import { toast } from '../toast'
import { VMETA } from '../verdict'

const shortVerdict = (v: VerdictType): string =>
  v === 'INSUFFICIENT_SIGNAL' ? 'INSUFF.' : VMETA[v].label

const fmtFullDate = (iso: string): string =>
  new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })

// The persisted verdict-change log for one IPO (engine transition endpoint) — recorded as the
// verdict moved, most-recent-first. Never a re-score: each row is a real emission.
function VerdictHistory({ id }: { id: string }) {
  const { data } = useTransitionsFor(id)
  const rows = data ?? []
  return (
    <div className="card">
      <h3 className="sec">Verdict history</h3>
      {rows.length ? (
        <ul className="vhist">
          {rows.map((t, i) => (
            <li key={i}>
              <span className="vh-date mono">{fmtFullDate(t.asof)}</span>
              <span className={`vh-badge t-${VMETA[t.from_verdict ?? 'INSUFFICIENT_SIGNAL'].cls}`}>
                {shortVerdict(t.from_verdict ?? 'INSUFFICIENT_SIGNAL')}
              </span>
              <span className="vh-arrow">→</span>
              <span className={`vh-badge t-${VMETA[t.to_verdict].cls}`}>
                {shortVerdict(t.to_verdict)}
              </span>
              {t.crossed_into_apply && <span className="vh-cross">crossed into APPLY</span>}
              {t.probability != null && (
                <span className="vh-p mono">{Math.round(t.probability * 100)}%</span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <div className="pending">
          No verdict changes recorded — the engine has not moved this call.
        </div>
      )}
    </div>
  )
}

const Check = () => (
  <svg viewBox="0 0 24 24">
    <path d="M20 6 9 17l-5-5" />
  </svg>
)

const fmtWhen = (iso: string): string =>
  new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })

// v3 V3-8 — the bid lot as an INDICATIVE planning figure, never an exact reported value. NSE gives
// lot_size on 0% of IPOs, so this is the sole (Upstox) source, corroborated only against the SEBI
// ~₹14–15k minimum-application band — so it wears the '≈'/'approx' face of an estimate. No source is
// named (the app doesn't attribute providers). The app places no bids; the broker enforces the true
// lot at application time, so an off-by-one is a small planning delta, not an invalid bid. Amount is
// lot × the band top (the cut-off), the standard maximum application.
function lotIndicative(ctx: IpoContextView | undefined, bandHigh: number): string {
  if (!ctx || ctx.lot_state === 'not_loaded') return '—'
  if (ctx.lot_state === 'stale') return 'unknown — data stale'
  if (ctx.lot_state === 'unpublished' || ctx.lot_size == null) return 'not published yet'
  const amount = Math.round(ctx.lot_size * bandHigh).toLocaleString('en-IN')
  return `≈ ${ctx.lot_size} shares · approx ₹${amount}`
}

// v3 V3-11 — honest degradation for a plain reference field (isin / industry): the value if present,
// else why it's absent (stale cache vs genuinely not available), never a bare blank that lies.
function refField(value: string | null, state: IpoContextView['isin_state']): string {
  if (state === 'stale') return 'unknown — data stale'
  if (state === 'unpublished' || value == null) return 'not available'
  return value
}

// v3 V3-11 — ISIN + industry: plain display metadata from the per-IPO Upstox context cache (never a
// model input, no source named). The card itself always renders (same layout on every Detail page,
// regardless of IPO) — only the field text degrades, via refField's own per-field state. Grouped as
// one small card next to the filed documents.
function ContextRef({ ctx }: { ctx: IpoContextView | undefined }) {
  if (!ctx) return null // don't flash while the context query is still loading
  return (
    <div className="card">
      <h3 className="sec">Reference</h3>
      <div className="kv">
        <div className="r">
          <span
            className="k gl"
            data-tip="International Securities Identification Number — the security's unique code, used when checking allotment or holdings. Reference only."
          >
            ISIN
          </span>
          <span className="v mono">{refField(ctx.isin, ctx.isin_state)}</span>
        </div>
        <div className="r">
          <span
            className="k gl"
            data-tip="The company's industry/sector classification. Context only — it is not a model input."
          >
            Industry
          </span>
          <span className="v">{refField(ctx.industry, ctx.industry_state)}</span>
        </div>
      </div>
    </div>
  )
}

// v3 V3-5 — the filed RHP link. Display/routing only (from the per-IPO Upstox context cache, never a
// model input). Labelled the *Red Herring Prospectus* explicitly — the final offer document, never a
// generic "prospectus" and never the draft (DRHP was dropped as unusable). Opens one-click for any
// https RHP — a public regulatory filing, not a PAN-entry surface, so every RHP gets the same button
// regardless of whether SEBI or the issuer hosts it. A missing link distinguishes "not filed yet"
// from "cache is stale".
function RhpLink({ ctx }: { ctx: IpoContextView | undefined }) {
  if (!ctx) return null // don't flash while loading
  const { rhp_url, rhp_state, refreshed_at } = ctx
  return (
    <div className="card">
      <h3 className="sec">Filed documents</h3>
      {rhp_state === 'present' && isAllowedRhpUrl(rhp_url) ? (
        <button className="btn al-check" onClick={() => openExternalUrl(rhp_url as string, 'rhp')}>
          Red Herring Prospectus (RHP) ↗
        </button>
      ) : rhp_state === 'present' && rhp_url ? (
        <div className="rhp-inert">
          <span className="rhp-lab">Red Herring Prospectus (RHP)</span>
          <span className="al-nolink" title="Not a valid https link — open it manually">
            open manually · <span className="mono al-url">{rhp_url}</span>
          </span>
        </div>
      ) : rhp_state === 'stale' ? (
        <div className="pending">
          RHP link unknown — the context cache is stale (last refreshed{' '}
          {refreshed_at ? fmtWhen(refreshed_at) : '—'}). Run <span className="mono">
            scripts/refresh_context.py
          </span> to check; it isn't shown as "not filed" because we haven't looked.
        </div>
      ) : rhp_state === 'unpublished' ? (
        <div className="pending">RHP not filed yet for this IPO.</div>
      ) : (
        <div className="pending">
          RHP link not loaded — run <span className="mono">scripts/refresh_context.py</span>.
        </div>
      )}
    </div>
  )
}

// Subscription multiples arrive as raw floats (e.g. 3.477239327931627 = bid ÷ offered). Show them
// the way the exchanges do: 2 decimals, trailing zeros trimmed — 3.48×, 19.22×, 242×.
const fmtMult = (v: number): string => v.toFixed(2).replace(/\.?0+$/, '')
const x = (v: number | null): string => (v != null ? `${fmtMult(v)}×` : '—')

// Readable label for each contribution key, enriched with the feature value where available.
function contribLabel(key: string, f: IPOFeatures): string {
  switch (key) {
    case 'qib_sub':
      return f.qib_sub != null ? `QIB ${fmtMult(f.qib_sub)}×` : 'QIB'
    case 'nii_sub':
      return f.nii_sub != null ? `NII ${fmtMult(f.nii_sub)}×` : 'NII'
    case 'retail_sub':
      return f.retail_sub != null ? `Retail ${fmtMult(f.retail_sub)}×` : 'Retail'
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

const _SUB_KEYS = new Set(['qib_sub', 'nii_sub', 'retail_sub'])

// Plain-language headline for the verdict, composed from the SAME signed contributions the engine
// produced (already shown as the bars below). Presentation only — it verbalizes the dominant driver,
// derives no new number, and the exact engine reason string stays verbatim beneath it.
function plainLead(d: IPODetail): string | null {
  const entries = Object.entries(d.contributions).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
  if (!entries.length) return null
  const [key, val] = entries[0]
  const pos = val >= 0
  const phrases: Record<string, [string, string]> = {
    qib_sub: ['Strong institutional demand', 'Soft institutional demand'],
    nii_sub: ['Strong high-net-worth (NII) demand', 'Weak high-net-worth (NII) demand'],
    retail_sub: ['Strong retail demand', 'Thin retail demand'],
    anchor_quality: ['High-quality anchor book', 'Weak anchor backing'],
    relative_valuation: ['Attractively valued vs peers', 'Richly valued vs peers'],
    ofs_fraction: ['Mostly fresh-capital raise', 'Heavy offer-for-sale'],
    market_regime: ['Supportive market backdrop', 'Cold market backdrop'],
  }
  const pair = phrases[key]
  if (!pair) return null
  let tail = contribLabel(key, d.features)
  if (_SUB_KEYS.has(key)) {
    // Whole-× to match the engine's grounded-reason line (which rounds), not the 2-decimal
    // subscription-card value — so the headline and the reason beneath it never disagree.
    const v =
      key === 'qib_sub' ? d.features.qib_sub : key === 'nii_sub' ? d.features.nii_sub : d.features.retail_sub
    const name = key === 'qib_sub' ? 'QIB' : key === 'nii_sub' ? 'NII' : 'Retail'
    if (v != null) tail = `${name} ${Math.round(v)}× ${v >= 1 ? 'oversubscribed' : 'undersubscribed'}`
  }
  return `${pos ? pair[0] : pair[1]} — ${tail}`
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
  const { data: d, isLoading, isError, refetch } = useIpo(id)
  const { data: ctx } = useIpoContext(id) // display-only Upstox context (RHP, lot) — never scored
  // v3-DP DP-3b — the banked subscription history for the trend chart. Display-only; it reaches a
  // chart and never the scorer (the B1 wall). `isLoading` is read so the chart can show a loading
  // state instead of flashing the empty frame, which would read as "never recorded" and then change
  // its mind — the engine's VM call can take up to ~10s before it answers "unavailable".
  const series = useSubscriptionSeries(id)
  const [copied, setCopied] = useState(false)

  if (isLoading) return <Loading label="Loading verdict…" />
  if (isError || !d)
    return (
      <div className="state">
        <h3>Couldn't load this IPO</h3>
        <p>The engine isn't responding.</p>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
          <button className="btn" onClick={() => void refetch()}>
            Retry
          </button>
          <button className="btn" onClick={onBack}>
            Back
          </button>
        </div>
      </div>
    )

  const { record: r, verdict: v, features: f } = d
  const m = VMETA[v.verdict]
  const isKill = v.kill_flags.length > 0
  const showNumber = v.probability != null && !isKill
  const pct = v.probability != null ? Math.round(v.probability * 100) : null
  // Graded regime caveat (v2 B9): cold OR the milder soft tier — both render in the caveat box.
  const regimeCaveat = v.watch.find((w) => /cold market|softening market/i.test(w))
  const watch = v.watch.filter((w) => !/cold market|softening market/i.test(w))
  const fresh = r.ofs_fraction != null ? `${Math.round((1 - r.ofs_fraction) * 100)} / ${Math.round(r.ofs_fraction * 100)}` : '—'
  const band = `₹${r.price_band_low}–${r.price_band_high}`
  const lead = plainLead(d)
  // Allotment odds are a conservative FLOOR (retail applicants average >1 lot, so real odds are
  // usually higher) — framed as "at least ~X%", visually distinct from the calibrated probability.
  const allot = d.retail_allotment_odds
  const allotFloor =
    allot == null ? null : allot >= 0.995 ? '~100%' : allot >= 0.01 ? `~${Math.round(allot * 100)}%` : '<1%'

  const copy = () => {
    const txt = `${r.name} — ${v.verdict}${showNumber ? ` (${pct}% calibrated)` : ''}. ${v.reason}. Advisory only, not financial advice.`
    void navigator.clipboard?.writeText(txt)
    setCopied(true)
    toast('Verdict copied to clipboard')
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
              <div
                className="gate"
                data-tip="The calibrator passed its out-of-sample reliability check (the 70% bucket lists positive ~70% of the time), so this probability is trustworthy. Until it passes, no number is shown."
              >
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
            <div className="mono" style={{ fontSize: 11, letterSpacing: '.07em', textTransform: 'uppercase', color: 'var(--tx2)', whiteSpace: 'nowrap' }}>
              Calibrated P(positive listing)
            </div>
            <div className="bigmeter">
              <i style={{ width: `${pct}%` }} />
            </div>
            <div className="mono" style={{ color: 'var(--tx2)', fontSize: 12.5, whiteSpace: 'nowrap' }}>
              {pct} / 100
            </div>
          </div>
        )}

        <div className="card">
          <h3 className="sec">Why this verdict</h3>
          {lead && <p className="reason-lead">{lead}</p>}
          <p className="reason-body">
            <span className="reason-src">grounded reason</span>
            {v.reason}
          </p>
          <h3 className="sec" style={{ marginTop: 22 }}>
            What drove this
          </h3>
          <Contributions d={d} />
        </div>

        <VerdictHistory id={id} />

        <RhpLink ctx={ctx} />

        <ContextRef ctx={ctx} />

        <div className="card">
          <h3 className="sec">{f.book_closed ? 'Subscription (final)' : 'Subscription (live)'}</h3>
          <div className="kv">
            <div className="r">
              <span className="k gl" data-tip="Qualified Institutional Buyers — banks, mutual funds, insurers. Their subscription multiple is the strongest institutional-confidence signal.">QIB</span>
              <span className="v" style={{ color: 'var(--apply)' }}>{x(r.qib_sub)}</span>
            </div>
            <div className="r">
              <span className="k gl" data-tip="Non-Institutional Investors (HNIs). Split into small (sNII, ₹2–10L) and big (bNII, over ₹10L) buckets.">NII</span>
              <span className="v">{x(r.nii_sub)}</span>
            </div>
            {r.nii_small_sub != null && (
              <div className="r sub">
                <span className="k">↳ sNII (₹2–10L)</span>
                <span className="v">{x(r.nii_small_sub)}</span>
              </div>
            )}
            {r.nii_big_sub != null && (
              <div className="r sub">
                <span className="k">↳ bNII (over ₹10L)</span>
                <span className="v">{x(r.nii_big_sub)}</span>
              </div>
            )}
            <div className="r">
              <span className="k gl" data-tip="Retail Individual Investors — bids up to ₹2 lakh. A retail-led book is a weaker signal than a QIB-led one.">Retail</span>
              <span className="v">{x(r.retail_sub)}</span>
            </div>
            {allotFloor != null && (
              <div className="alloc">
                <div className="alloc-head">
                  <span
                    className="alloc-lab gl"
                    data-tip="Estimated chance a 1-lot retail application receives an allotment ≈ min(1, 1 ÷ retail subscription). A conservative FLOOR: it under-states the real odds because retail applicants average more than one lot. This is the chance of GETTING SHARES — a different thing from the calibrated probability of a positive listing shown at the top."
                  >
                    Retail allotment odds · est. floor
                  </span>
                  <span className="alloc-val mono">≥ {allotFloor}</span>
                </div>
              </div>
            )}
            {r.overall_sub != null && (
              <div className="r">
                <span className="k gl" data-tip="Total demand across all categories, weighted by each category's reserved portion of the book.">Overall</span>
                <span className="v mono" style={{ fontWeight: 700 }}>{x(r.overall_sub)}</span>
              </div>
            )}
          </div>
          <h3 className="sec" style={{ marginTop: 18 }}>
            Issue structure
          </h3>
          <div className="kv">
            <div className="r">
              <span className="k gl" data-tip="Fresh = new capital raised for the company. OFS = Offer For Sale, existing holders cashing out. A high OFS share is a mild negative.">Fresh / OFS</span>
              <span className="v">{fresh}</span>
            </div>
            <div className="r">
              <span className="k gl" data-tip="A 0–1 score of the anchor investors' reputation and lock-in length. Higher means stronger institutional endorsement before the book opens.">Anchor quality</span>
              <span className="v" style={{ color: 'var(--apply)' }}>
                {f.anchor_quality != null ? f.anchor_quality.toFixed(2) : '—'}
              </span>
            </div>
            <div className="r">
              <span
                className="k gl"
                data-tip="Indicative bid lot and the approximate application amount at the cut-off price — a planning estimate, not an exact figure. The app places no orders; your broker enforces the exact lot when you apply."
              >
                Lot (indicative)
              </span>
              <span className="v">{lotIndicative(ctx, r.price_band_high)}</span>
            </div>
          </div>
        </div>

        <SeriesChart
          view={series.data}
          state={chartState(series.data, series.isLoading)}
          bookClosed={!!f.book_closed}
        />

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

        {regimeCaveat && (
          <div className="caveat">
            <IconAlert />
            <span>
              <b>{regimeCaveat.charAt(0).toUpperCase() + regimeCaveat.slice(1)}.</b> Annotation
              only; it does not change the number above.
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
