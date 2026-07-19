// Subscription-history chart logic (v3-DP DP-3b) — PURE, so `node --test` covers the rules that
// decide what the user is told. The chart component renders; every judgement lives here.
//
// THE CENTRAL RULE: render off `state`, NEVER off `samples.length`. An empty list cannot tell
// "nothing was ever recorded" from "we could not reach the server", and those are different truths —
// the first is a fact about the world, the second a fact about our reachability. DP-3a already
// separated them; collapsing them here would throw that away at the last hop.
//
// WIRE VALUES vs ON-SCREEN WORDS are deliberately separate concerns:
//   * `SeriesState` values (recorded / not_recorded / unavailable / not_loaded) are the DP-3a
//     contract. They appear in test assertions and in engine log lines, where `state=unavailable` is
//     exactly the precision an operator wants. They do not change.
//   * `MESSAGES` is the ONE place those states become sentences a retail user reads. Internal terms
//     ("data plane", "trajectory", "in this build") must not reach the screen — a user does not know
//     what a data plane is, and "trajectory" is our word, not theirs.

import type { SeriesSample, SeriesState, SeriesView } from './api/types'

/** What the chart should draw. `loading` is a UI state, not a wire state — hence the union. */
export type ChartState = SeriesState | 'loading'

export interface ChartCopy {
  /** The headline line inside the frame. */
  title: string
  /** Optional second line. Absent where one sentence says it all. */
  detail?: string
  /** Amber treatment — reserved for "we could not find out", never for honest absence. */
  warn?: boolean
}

/**
 * On-screen copy for every non-plotting state, in ONE place.
 *
 * `not_recorded` and `unavailable` must stay distinguishable IN THE WORDS, not merely in the state
 * value the user cannot see: an empty chart that says "nothing recorded" when the truth is "we
 * could not reach the server" is the UI lying with a straight face.
 */
export const MESSAGES: Record<Exclude<ChartState, 'recorded'>, ChartCopy> = {
  not_recorded: {
    title: 'No subscription history recorded',
    detail: 'This IPO closed before we started recording.',
  },
  unavailable: {
    // Says what went wrong (a connection), not what we do or don't know about the data. An earlier
    // draft spelled out "this doesn't mean nothing was recorded" — true, but it explains OUR
    // bookkeeping to someone who never had the wrong idea. The distinction from `not_recorded`
    // survives without it: this names a server problem and wears amber, that names the IPO's own
    // history and does not. A reader is told a fetch failed, which is the whole of what they need.
    title: 'Subscription history unavailable',
    detail: "Couldn't reach the server — try again shortly.",
    warn: true,
  },
  loading: { title: 'Loading subscription history…' },
  not_loaded: { title: "Subscription history isn't available here." },
}

/** Map the fetch outcome to what the chart draws. Reads `state`; never counts samples. */
export function chartState(view: SeriesView | undefined, isLoading: boolean): ChartState {
  if (isLoading) return 'loading'
  // A failed fetch (engine unreachable, not the VM) is the same user-facing truth as the VM being
  // unreachable: we could not find out. It is NOT "nothing was recorded".
  if (!view) return 'unavailable'
  return view.state
}

/**
 * Split samples into contiguous runs, breaking wherever a cycle was missed.
 *
 * This is what makes a fetch gap render as a BROKEN line. DP-1 deliberately banks nothing on a
 * failed fetch — an honest hole rather than a fabricated row — so the chart must not quietly bridge
 * it. Drawing one polyline per run means the gap is absence of geometry, not a styled segment.
 *
 * The threshold is relative (1.8x the median interval) rather than a hardcoded 30 minutes, so it
 * still holds if the ingest cadence is ever retuned — the recorder's cadence is not this module's
 * business to know.
 */
export function splitRuns(samples: readonly SeriesSample[]): SeriesSample[][] {
  if (samples.length < 2) return samples.length ? [[...samples]] : []
  const ts = samples.map((s) => new Date(s.captured_at).getTime())
  const deltas = ts.slice(1).map((t, i) => t - ts[i]).sort((a, b) => a - b)
  const median = deltas[Math.floor(deltas.length / 2)] || 0
  const runs: SeriesSample[][] = [[samples[0]]]
  for (let i = 1; i < samples.length; i++) {
    if (median > 0 && ts[i] - ts[i - 1] > median * 1.8) runs.push([samples[i]])
    else runs[runs.length - 1].push(samples[i])
  }
  return runs
}

/**
 * The per-IPO freshness chip — from THIS curve's own clock (DP-3a's `refreshed_at`), never the
 * app-global updated-time, which would misreport a finished curve as stale.
 */
export function freshnessLabel(view: SeriesView, bookClosed: boolean): string {
  const n = view.samples.length
  const noun = n === 1 ? 'reading' : 'readings'
  return `${bookClosed ? 'complete' : 'updating'} · ${n} ${noun}`
}

/** Format a subscription multiple for an axis tick or the legend. */
export function fmtMultiple(v: number): string {
  if (v >= 10) return `${Math.round(v)}x`
  return `${v.toFixed(2).replace(/0$/, '')}x`
}
