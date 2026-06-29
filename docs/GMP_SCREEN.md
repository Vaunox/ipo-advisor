# GMP Level-Only Screening (nikhilraj Kaggle) — replication lane, NOT the Phase-5 answer

*Independent dataset, its own gross/open-based label, never fed to our calibrator. Tests one thing: does GMP **level** add discrimination **incremental to subscription**? AUC is the apples-to-apples metric (label differs from ours). Not financial advice.*

## Result (walk-forward OOS)

- Dataset: **152** IPOs (2020–2023), **92** out-of-sample.
- **AUC, total-subscription alone:** 0.749
- **AUC, subscription + GMP level:** 0.882
- **Marginal lift from GMP level:** **+0.133** (95% paired-bootstrap CI [+0.062, +0.216]) — GMP **does** add signal beyond subscription.

## Provenance & leakage (read this before the number)

- **Subscription column is TOTAL, not QIB** — baseline is total demand, not QIB specifically (a clean QIB test would need merging our official data, disallowed here).
- **The single GMP value is almost certainly final/near-listing (LEAKY).** GMP-implied vs actual listing correlate **~0.92** with **84%** direction match — far tighter than as-of-close GMP (~70–75% directional, magnitude often off). So any lift above is an **optimistic upper bound**, not the as-of-close truth.

## What this test CANNOT answer

- **Nothing about GMP slope or the GMP-collapse kill-flag** — no day-by-day data here.
- A null result rules out **level-only** GMP, not GMP as a whole.
- The 2020–2023 window is **hot-market-skewed**, so it says little about cold regimes.

## Verdict — is the full day-by-day slope scraper worth building?

**INCONCLUSIVE — a lift appears, but the GMP here is leaky (final/near-listing), so it is an upper bound, not proof that as-of-close GMP helps. This convenient dataset cannot settle the Phase-5 question; only a true as-of-close series can.**

Either way, this convenient level-only dataset does not redefine Phase 5: the Phase-5 question (does as-of-close GMP level + slope earn its weight by improving calibration) still requires a real, point-in-time, day-by-day series and the re-calibration gate.