# B8 Idea 1 — conformal uncertainty bands (honesty layer, never a new probability)

> ⛔ **SHELVED — BUILT + COVERAGE-VALIDATED, CHOSE NOT TO SHIP (2026-07-04).** The bands work (this
> report is the evidence), but they were only a *quantitative refinement* of the message the cold
> flag (B9 tiers + B2 VIX) already delivers actionably — "be more cautious in unfamiliar markets" —
> and were judged not worth the core-module rework to ship properly. **Nothing reached main:** the
> shipped scorer, calibrator, frontend, and cold flag are exactly as they were; B8 never touched
> them. The full code (module, wiring, tests, and the estimate-vs-outcome-band fork below) is
> preserved off-main under the git tag **`b8-conformal-shelved`** for anyone who revisits it. Idea 2
> (regime-aware calibration) remains deferred. See `V2_PROGRESS.md`.

*Answers "how much should I trust this probability?" with a **narrow, symmetric range** around the
calibrated point estimate — e.g. "78%, realistic range 70–86%" — that **widens when the IPO's
market is unfamiliar/cold** (fewer similar IPOs pin down the rate) and narrows when familiar. It
is the epistemic uncertainty in the **rate estimate**, the quantitative companion to the B9/B2
cold flag. Module: `src/ipo/calibration/conformal.py`; fit/validate: `scripts/run_conformal.py`.
Engineering reference, not financial advice.*

## Method — distribution-free conformal, at the *rate* level

Normalized split-conformal with the nonconformity taken on the **rate**, not the binary outcome:

- ``r_local(x)`` — the kernel-weighted local outcome rate (best local estimate of the true rate),
- ``σ(x) = sqrt(p̂(1−p̂) / density(x))`` — the rate's standard error given the local evidence
  (``density`` = kernel-weighted count of similar IPOs in predicted-prob × market-regime space),
- nonconformity ``s = |r_local(x) − p̂| / σ(x)``; the conformal quantile ``q`` sets the width so
  the band covers the true local rate at its claimed rate.

Because a well-calibrated model's local rate is *close* to ``p̂``, the bands are **narrow**; ``σ``
supplies the adaptivity — tiny when ``p̂`` is confident (near 0/1) or the regime is well-populated,
large where evidence is thin (cold/unfamiliar), which is what widens the band. No per-regime
calibration is needed (that is Idea 2, deferred).

## Gate 1 — no scoring impact: MAX |Δprob| = 0.0 (proven, non-vacuous)

`tests/integration/test_conformal_wiring.py` runs two live engines over the whole backfill — bands
wired vs not — and asserts **every calibrated probability and verdict is byte-for-byte identical
(max |Δprob| = 0.0)** while the wired engine *does* attach bands. The band is computed downstream of
the final `verdict.probability`; the scorer and calibrator are untouched.

## Gate 2 — the bands are honest: rate-coverage claimed ≈ realized

Held-out rate-coverage (repeated cal/test splits, N=298 OOS on the 2017–2026 sample):

| Claimed | Realized (band contains the true local rate) | Mean width |
|---|---|---|
| **80%** | **80%** | 0.33 |

The band contains the true local rate ~as often as it claims — a genuine conformal guarantee.

## Behavior — narrow when confident/familiar, wider when uncertain/cold

Real examples from the 358-IPO sample (APPLY mean width: **warm ±0.08, cold ±0.12**):

| IPO | p̂ | regime | band | note |
|---|---|---|---|---|
| Nazara / Burger King / EaseMyTrip | ~100% | warm | **[99%, 100%]** | near-certain + familiar → very tight |
| **Crizac** (Jul 2025) | 93% | **warm +1.0** | **[83%, 100%]** | confident, familiar |
| **Senores** (Dec 2024) | 94% | **cold −1.0** | **[74%, 100%]** | *same confidence, cold → wider* |
| HDBFS (Jul 2025) | 83% | warm | [67%, 99%] | lower confidence → wider, still symmetric |
| Aether / Innovision | 60% | cold −1.0 | [10%, 100%] | uncertain **and** cold → very wide (honest) |

- **Widens in cold at matched confidence:** Senores (94%, cold) `[74,100]` vs Crizac (93%, warm)
  `[83,100]`. Across APPLY IPOs cold bands average ~50% wider than warm.
- **Narrow + symmetric where it matters:** a confident, familiar APPLY IPO gets a ±0.08 range
  (Crizac `[83,100]`); the band is symmetric about `p̂` (HDBFS `[67,99]`) except when `p̂` is close
  to 1, where the upper end naturally meets the 100% ceiling.

## Why the estimate band, not an outcome band (the fork, on the record)

The original brief straddled two objects. An **outcome-coverage** band (validated by "the binary
listing outcome falls inside ~X%") was built first and is coverage-valid — but because a listing is
0/1, that math forces **asymmetric, wide floors** (e.g. 83% → `[42,100]`, upper pinned at 100%) that
read as a worst-case bound, not a confidence range, and clash with the detail page. B8's purpose is
"how much to trust this number" — the **epistemic uncertainty in the rate estimate** — which is the
narrow, symmetric range this ships. It is validated by **rate-coverage** (does the band contain the
true rate), the correct test for what an estimate band claims. The outcome-band version was
discarded, not merged; this note records the choice so the fork isn't re-litigated.
