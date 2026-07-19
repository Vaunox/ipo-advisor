// Subscription trend chart (v3-DP DP-3b / the deferred V3-9) — RENDER ONLY.
//
// Every judgement lives in `../series.ts` so `node --test` can cover it; this file turns those
// decisions into SVG. Hand-rolled, in an `ss-*` namespace mirroring the app's existing `rd-*`
// reliability diagram — no charting library and no new visual language (V3-15).
//
// IT SHOWS THE BOOK, NEVER A SCORE. Raw subscription multiples over time, nothing derived: no
// probability-over-time, no verdict-over-time, no scored quantity computed from the trajectory.
// That would be re-scoring on partial books (the parked #1 hazard) and would blur the line between
// display and model that the whole of v3-DP exists to keep sharp.

import type { SeriesSample, SeriesView } from '../api/types'
import { type ChartState, MESSAGES, fmtMultiple, freshnessLabel, splitRuns } from '../series'

const PAD = { l: 34, r: 12, t: 10, b: 22 }
const W = 390
const H = 170

const SERIES = [
  { key: 'retail_sub', cls: 'ss-ret', label: 'Retail' },
  { key: 'nii_sub', cls: 'ss-nii', label: 'NII' },
  // QIB is drawn LAST so it sits on top — it is the strongest signal, and the Subscription card
  // already gives it this same green.
  { key: 'qib_sub', cls: 'ss-qib', label: 'QIB' },
] as const

function fmtTime(iso: string): string {
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getDate())}/${p(d.getMonth() + 1)} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function Frame({ children }: { children?: React.ReactNode }) {
  // The frame renders in EVERY state. An empty plotting field inside real chrome reads as "nothing
  // to show"; a missing card would read as "this IPO has no such thing", which is a different and
  // wrong claim.
  return (
    <svg className="ss-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Subscription trend">
      <line className="ss-axis" x1={PAD.l} y1={PAD.t} x2={PAD.l} y2={H - PAD.b} />
      <line className="ss-axis" x1={PAD.l} y1={H - PAD.b} x2={W - PAD.r} y2={H - PAD.b} />
      {children}
    </svg>
  )
}

function Message({ state }: { state: Exclude<ChartState, 'recorded'> }) {
  const copy = MESSAGES[state]
  const cx = (W + PAD.l) / 2
  return (
    <Frame>
      {state === 'loading' && (
        <rect
          className="ss-shimmer"
          x={PAD.l + 1}
          y={H - PAD.b - 46}
          width={W - PAD.l - PAD.r - 2}
          height={44}
          rx={3}
        />
      )}
      <text className={`ss-msg${copy.warn ? ' warn' : ''}`} x={cx} y={copy.detail ? H / 2 - 4 : H / 2 + 2} textAnchor="middle">
        {copy.title}
      </text>
      {copy.detail && (
        <text className="ss-sub" x={cx} y={H / 2 + 15} textAnchor="middle">
          {copy.detail}
        </text>
      )}
    </Frame>
  )
}

function Plot({ samples }: { samples: SeriesSample[] }) {
  const ts = samples.map((s) => new Date(s.captured_at).getTime())
  const t0 = ts[0]
  const t1 = ts[ts.length - 1]
  const vals = samples.flatMap((s) => [s.qib_sub, s.nii_sub, s.retail_sub]).filter((v): v is number => v != null)
  const vmax = Math.max(...vals, 0.1) * 1.15
  const X = (t: number) => (t1 === t0 ? PAD.l + (W - PAD.l - PAD.r) / 2 : PAD.l + ((t - t0) / (t1 - t0)) * (W - PAD.l - PAD.r))
  const Y = (v: number) => H - PAD.b - (v / vmax) * (H - PAD.b - PAD.t)
  const runs = splitRuns(samples)
  const gaps = runs.length - 1

  return (
    <Frame>
      {[0, vmax / 2, vmax].map((v, i) => (
        <g key={`y${i}`}>
          <line className="ss-grid" x1={PAD.l} y1={Y(v)} x2={W - PAD.r} y2={Y(v)} />
          <text className="ss-tick" x={PAD.l - 5} y={Y(v) + 3} textAnchor="end">
            {fmtMultiple(v)}
          </text>
        </g>
      ))}
      <text className="ss-tick" x={X(t0)} y={H - PAD.b + 11} textAnchor="start">
        {fmtTime(samples[0].captured_at)}
      </text>
      <text className="ss-tick" x={X(t1)} y={H - PAD.b + 11} textAnchor="end">
        {fmtTime(samples[samples.length - 1].captured_at)}
      </text>
      {gaps > 0 && (
        // Named, so a break reads as recorded absence rather than a rendering artefact.
        <text className="ss-gapnote" x={W - PAD.r} y={PAD.t + 8} textAnchor="end">
          {gaps} gap{gaps > 1 ? 's' : ''} — not recorded
        </text>
      )}
      {SERIES.map(({ key, cls, label }) =>
        runs.map((run, ri) => {
          const pts = run.filter((s) => s[key] != null)
          if (!pts.length) return null
          // A one-sample run has no line to draw; a dot keeps a sparse series visible instead of
          // silently rendering nothing.
          if (pts.length === 1) {
            const s = pts[0]
            return (
              <circle key={`${key}-${ri}`} className={`ss-dot ${cls}`} cx={X(new Date(s.captured_at).getTime())} cy={Y(s[key] as number)} r={2.6}>
                <title>{`${label} ${fmtMultiple(s[key] as number)} · ${fmtTime(s.captured_at)}`}</title>
              </circle>
            )
          }
          return (
            <polyline key={`${key}-${ri}`} className={cls} points={pts.map((s) => `${X(new Date(s.captured_at).getTime()).toFixed(1)},${Y(s[key] as number).toFixed(1)}`).join(' ')}>
              <title>{`${label} · ${pts.length} readings · ${fmtMultiple(pts[0][key] as number)} → ${fmtMultiple(pts[pts.length - 1][key] as number)}`}</title>
            </polyline>
          )
        }),
      )}
    </Frame>
  )
}

export function SeriesChart({ view, state, bookClosed }: { view: SeriesView | undefined; state: ChartState; bookClosed: boolean }) {
  // Takes the RESOLVED state, not the raw isLoading flag. Passing both would let them disagree —
  // and the disagreement would surface as the chart claiming "nothing recorded" while still
  // loading, which is the exact lie the loading state exists to prevent.
  const plotting = state === 'recorded' && view && view.samples.length > 0
  const last = plotting ? view.samples[view.samples.length - 1] : undefined

  return (
    <div className="card ss-card">
      <div className="ss-head">
        <h3 className="sec" style={{ margin: 0 }}>
          Subscription Trend
        </h3>
        {plotting && view && (
          <span className={`ss-fresh ${bookClosed ? 'done' : 'live'}`}>
            <span className="dot" />
            {freshnessLabel(view, bookClosed)}
          </span>
        )}
      </div>

      {/* The grid stretches this card to its row's tallest sibling (the ~535px Subscription card),
          and the plot has a FIXED intrinsic height, so leftover space is unavoidable here without
          breaking the page's matched-bottom-edge rule. Centring splits it above and below, which
          reads as deliberate composition; all of it dumped underneath read as an unfinished card. */}
      <div className="ss-body">
        {plotting && view ? (
          <Plot samples={view.samples} />
        ) : (
          <Message state={state as Exclude<ChartState, 'recorded'>} />
        )}

        {plotting && last && (
          // The legend carries each series' LATEST value. On real data NII and Retail can sit
          // within 1% of each other (cmll: 1.5927 vs 1.5776 — about a pixel apart), so the lines
          // genuinely coincide; without the numbers a reader would think a series was missing
          // rather than overlapping.
          <div className="ss-legend">
            {[...SERIES].reverse().map(({ key, cls, label }) => (
              <span className="k" key={key}>
                <i className={cls} />
                {label}
                <b>{last[key] == null ? '—' : fmtMultiple(last[key] as number)}</b>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
