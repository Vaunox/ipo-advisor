# B9 — Graded regime-flag tiers (annotation-only) — build + byte-equality proof

*v2 B9. Replace the binary cold-market flag with graded **normal / soft / cold** tiers, each with
its own caveat. Pure annotation (`market_regime` scorer weight **0**) — the thin-cold-sample problem
that sank per-regime *calibration* does **not** apply here, because nothing about the number changes.
No new data; no gate.*

## What was built

- **Tiers** (`model/verdict.py::regime_tier`): on the point-in-time `market_regime`,
  - `normal` — `market_regime > soft` (or unknown) → **no caveat**,
  - `soft` — `cold < market_regime ≤ soft` → *"softening market — ranking reliable, probability a
    touch less certain"*,
  - `cold` — `market_regime ≤ cold` → *"cold market — ranking reliable, probability less certain"*
    (**unchanged** from the binary flag; the UI keys on this phrase).
- **Boundaries**: `cold_regime_flag = −0.3` (existing) and a new **`soft_regime_flag = −0.15`** —
  **untuned round numbers, a-priori, NOT fit to listing outcomes** (config `verdict_thresholds`).
- **UI** (`Detail.tsx`): the caveat box now recognizes both tiers (`cold market | softening market`)
  and renders the actual tier text; the soft tier shows a milder, clearly-labelled caveat.

## It never touches the number — proven

The tier is computed **after** the probability, purely to pick a `watch` caveat — `market_regime`'s
scorer weight is 0, so the number and the verdict type cannot change.
`tests/integration/test_regime_tiers_wiring.py` proves it on the 311-IPO backfill: verdicts computed
with the regime present (graded tiers active) have the **same verdict type** and
**`MAX |Δprob| = 0.0`** (exact) versus verdicts with no regime at all — while the proof is
**non-vacuous**: both the soft and cold tiers are populated and their caveats actually appear in
`watch`. `tests/unit/test_regime_tiers.py` pins the tier boundaries.

## What the tiers do (311 backfill IPOs, trend-only regime)

| tier | count | caveat |
|---|---|---|
| normal | 239 | none |
| **soft** | **13** | "softening market — … a touch less certain" (**new**) |
| cold | 59 | "cold market — … less certain" (unchanged) |

The only change in behaviour: **13** IPOs that closed in a mildly-soft tape (`−0.3 < regime ≤ −0.15`)
— previously silent — now carry a *gentle* caveat. The 59 cold-flagged IPOs are untouched, and no
probability moves. A pure annotation refinement.

## Status

BUILT (B9). Green: ruff + black + mypy (116 files) + **245 tests** (240 + 5 new); `tsc --noEmit`
clean. Branch `b9-graded-regime-tiers` — **paused for review before merge** (Part I-B). No
calibration impact.
