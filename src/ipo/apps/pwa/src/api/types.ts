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
  // v3 finding-④: the Live→History resolution is OVERDUE — a silent strand (book closed but never
  // stamped listed past the expected day + buffer, or stamped but its price never backfilled).
  listing_overdue: boolean
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

// Allotment tab (v3 V3-6) — display/routing only, NEVER a model input. `registrar` is null when
// the cache has no entry for that IPO yet ("not yet available"); `available` is false when no cache
// has been loaded at all. `website` is the registrar's own allotment-check portal we deep-link out
// to — the user enters their PAN there, never in this app.
export interface RegistrarInfo {
  name: string | null
  short: string | null
  website: string | null
  email: string | null
  contact_number: string | null
  contact_name: string | null
}

// registrar_state (v3 V3-6): 'present' | 'unpublished' (cache current, not published yet) |
// 'stale' (cache predates this IPO / too old — absence unproven) | 'not_loaded' (no cache at all).
export type RegistrarState = 'present' | 'unpublished' | 'stale' | 'not_loaded'

export interface AllotmentRow {
  ipo_id: string
  name: string
  stage: string
  close_date: string
  listing_date: string | null
  registrar: RegistrarInfo | null
  registrar_state: RegistrarState
}

export interface AllotmentView {
  available: boolean
  refreshed_at: string | null
  rows: AllotmentRow[]
}

// One IPO's display-only Upstox context for the detail page (v3 V3-5) — never a model input.
// `rhp_url` is the Red Herring Prospectus (final offer doc), labelled as such in the UI. `rhp_state`
// inherits the shared staleness rule so a missing RHP distinguishes "not filed yet" from "cache
// predates the filing".
export interface IpoContextView {
  ipo_id: string
  available: boolean
  refreshed_at: string | null
  rhp_url: string | null
  rhp_state: RegistrarState
  // v3 V3-8 — the bid lot. NSE provides it on 0% of IPOs, so this is the sole source; shown as an
  // INDICATIVE planning figure (≈ N shares · approx ₹…), never as an exact reported value.
  lot_size: number | null
  lot_state: RegistrarState
  // v3 V3-11 — plain display reference metadata (no source named, honest degradation via *_state).
  isin: string | null
  isin_state: RegistrarState
  industry: string | null
  industry_state: RegistrarState
  registrar: RegistrarInfo | null
  registrar_state: RegistrarState
}

// Live-ingest freshness (v3 BUG 1 / Defect 2). `last_successful_ingest` is the ONLY value the UI
// may show as "Updated" — the last confirmed-good NSE pull, never a local API-read timestamp.
// `last_attempt_ok === false` means the store is still served but the feed is failing (stale +
// retrying). `live_ingest === false` = no live feed wired (timestamps null by construction).
export interface StatusView {
  live_ingest: boolean
  last_successful_ingest: string | null
  last_attempt: string | null
  last_attempt_ok: boolean | null
}
