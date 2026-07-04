# B2 — India VIX flag-enrichment (the safe half) — build + byte-equality proof

*v2 B2, safe half only (operator: build B2 fully). Blend India VIX into the regime **cold-market
flag** at **weight 0** — annotation-only, byte-equality proven. The **score-feature** half of B2
(VIX as a gated input) is a separate GATE-track step and is **not** done here.*

## What was built

- **Data.** `data/backfill/vix.csv` — India VIX daily closes, **4490 rows, 2008-03-03 → 2026-07-03**
  (Yahoo `^INDIAVIX`), sourced by `scripts/fetch_vix.py` (one-time backfill, append-only merge — not
  a standing recorder, so not subject to the forward-recording deferral). Bundled in the engine spec
  alongside `nifty.csv`.
- **`VixSeries`** (`calibration/regime.py`) — point-in-time `vol_stress_at(day) = clamp((vix -
  reference)/scale, -1, 1)`; elevated VIX → +1 (stressed), calm → -1. `reference=15`, `scale=15`
  (a-priori round numbers, NOT fit to outcomes).
- **The blend** (engine `_market_regime_at`, reusing the existing `compute_regime`):
  `market_regime = clamp(trend − vol_weight·max(0, vol_stress))` with the trend read kept at **full
  weight** (`trend_weight = 1.0`) and `vol_weight = 0.4`. It is **add-only** (operator decision): the
  stress is floored at 0, so elevated VIX only *tightens* the flag and a calm VIX **never lifts** a
  caveat the trend alone would raise. A neutral-/low-VIX day reproduces the old trend-only flag
  exactly. The cold flag fires at `market_regime ≤ −0.3`, unchanged.
- **Composition.** `build_service` loads `VixSeries` from `vix.csv` and injects it; `vix=None` keeps
  the old trend-only flag (backward compatible). Wired end-to-end into the live engine.

## It never touches the probability (weight 0) — proven

`market_regime`'s scorer weight is **0**, so blending VIX changes *which IPOs are flagged*, never
their number. `tests/integration/test_vix_flag_wiring.py` proves it on the 311-IPO backfill: the raw
scores are identical and the walk-forward **OOS probabilities are byte-for-byte identical** to the
trend-only / regime-free model (exact `==`, not a tolerance) — while a companion assertion confirms
the enrichment is **non-vacuous** (VIX genuinely flips the flag for ≥1 IPO, and the composed engine
actually blends it). The shipped calibrator is untouched.

## What VIX actually does (honest measurement, 311 backfill IPOs)

| | cold-flagged |
|---|---|
| trend-only (before) | 59 |
| trend + VIX (after) | **61** |

**Add-only:** VIX **added** the caveat to **2** IPOs — *Anand Rathi* and *Adani Wilmar*, both of which
closed during volatility spikes — and **removed it from none**. On the mostly-calm hot 2021–26 sample
that's a small, conservative tightening: the flag now also fires when a turbulent tape makes the
listing less predictable, but VIX never *drops* a caveat the trend alone raised. The caveat wording
("cold market — probability less certain") is unchanged (the UI keys on it); it's now driven by
weak-trend **and/or** high volatility.

*(Design decision, 2026-07-04: add-only, not symmetric. A symmetric blend — where calm VIX also
*removes* caveats — was considered and rejected in favour of never loosening an existing caveat.)*

## Honest prior (blueprint)

VIX may partly echo through cautious QIB bidding, so as a *score* feature it could be QIB-redundant —
but that's the separate **gated** half (B2.2), which must clear the with-vs-without gate and, per the
trust boundary, cross-check VIX against NSE-official before it can enter the number. This safe half
makes no such claim: it's a weight-0 annotation refinement, provable-harmless.

## Status

BUILT (B2 safe half). Green: ruff + black + mypy (114 files) + **240 tests** (234 + 6 new). Branch
`b2-vix-flag` — **paused for review before merge** (Part I-B). No calibration impact.
