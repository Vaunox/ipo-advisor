// TypeScript mirror of the engine's read-only API models (src/ipo/core/types.py,
// src/ipo/service/views.py). The UI displays these verbatim — it never re-derives a verdict
// or a probability (Invariant 1). `probability: null` is the withheld / uncalibrated case.

export type VerdictType = 'APPLY' | 'MARGINAL' | 'SKIP' | 'INSUFFICIENT_SIGNAL'

export interface Verdict {
  ipo_id: string
  verdict: VerdictType
  probability: number | null
  reason: string
  watch: string[]
  kill_flags: string[]
}

export interface SubscriptionPoint {
  asof: string
  qib: number | null
  nii: number | null
  retail: number | null
  overall: number | null
}

export interface IPORecord {
  ipo_id: string
  name: string
  segment: string
  price_band_low: number
  price_band_high: number
  lot_size: number | null
  issue_size_cr: number | null
  ofs_fraction: number | null
  open_date: string
  close_date: string
  listing_date: string | null
  qib_sub: number | null
  nii_sub: number | null
  retail_sub: number | null
  nii_small_sub: number | null
  nii_big_sub: number | null
  overall_sub: number | null
  subscription_progression: SubscriptionPoint[] | null
  issue_pe: number | null
  peer_median_pe: number | null
  promoter_litigation: boolean
  listing_open: number | null
  listing_close: number | null
}

export interface IPOFeatures {
  ipo_id: string
  asof: string
  qib_sub: number | null
  nii_sub: number | null
  retail_sub: number | null
  anchor_quality: number | null
  relative_valuation: number | null
  ofs_fraction: number | null
  market_regime: number | null
  book_closed: boolean
  flags: string[]
}

export interface IPODetail {
  record: IPORecord
  verdict: Verdict
  features: IPOFeatures
  contributions: Record<string, number>
  // v2 A3 — separate downstream display estimate: approx P(1-lot retail allotment),
  // min(1, 1/retail_sub). Distinct from `verdict.probability`; show as an estimate. null = unknown.
  retail_allotment_odds: number | null
}

export interface IPOListRow {
  ipo_id: string
  name: string
  segment: string
  issue_size_cr: number | null
  ofs_fraction: number | null
  issue_pe: number | null
  peer_median_pe: number | null
  open_date: string
  close_date: string
  listing_date: string | null
  verdict: VerdictType
  probability: number | null
  reason: string
  watch: string[]
  kill_flags: string[]
}

export interface HistoryRow {
  ipo_id: string
  name: string
  listing_date: string | null
  verdict: VerdictType
  probability: number | null
  net_return: number
  gross_return: number
  listed_positive: boolean
}

export interface ReliabilityBin {
  mean_predicted: number
  observed_rate: number
  count: number
}

export interface VerdictTransition {
  ipo_id: string
  name: string
  asof: string
  from_verdict: VerdictType | null
  to_verdict: VerdictType
  probability: number | null
  crossed_into_apply: boolean
}

export interface CalibrationView {
  version: string
  gate_passed: boolean
  source: string
  n: number
  base_rate: number | null
  ece: number | null
  brier: number | null
  auc: number | null
  bins: ReliabilityBin[]
}
