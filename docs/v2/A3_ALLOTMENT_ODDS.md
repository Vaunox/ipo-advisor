# A3 — Retail allotment odds (P(allotment) only) — build + honest accuracy back-check

*v2 A3, scoped down (operator decision, 2026-07-04) to **P(allotment) only** — the full
expected-value formula (gain-magnitude × odds − opportunity cost) was dropped: the gain term needs
a magnitude the model deliberately doesn't produce, and the ~3-day ASBA opportunity cost is
negligible (~₹8 on a typical application). Neither earns its complexity.*

## What was built

A **separate, downstream, display-only** estimate of the chance a minimum-lot retail application is
allotted, surfaced as a distinct figure next to the verdict so a user sees when a **strong IPO still
has near-zero allotment odds**.

- `src/ipo/service/allotment.py::retail_allotment_odds(retail_sub) → min(1, 1/retail_sub)` (or
  `None` when the retail multiple is unknown/non-positive). A pure function.
- Wired into `service/engine.py::detail()` → `service/views.py::IPODetail.retail_allotment_odds` →
  the API `/ipo/{id}` → the Detail screen (`apps/pwa/.../Detail.tsx`), labelled
  **"↳ Est. allotment odds (1 lot) ≈ X%"** with a tooltip stating it is an approximation that
  *under-states* real odds and is **not** the calibrated P(positive listing).

**It never touches the scorer or calibrator** — not because some Δprob is proven zero, but because
the odds are computed in a **separate code path** entirely outside scoring. The verdict/probability
are byte-for-byte unchanged (existing engine/verdict/calibration tests stay green).

## The formula is an approximation — and it's honestly off

`1/retail_sub` assumes every retail applicant bid exactly one lot. Real retail allotment is a
**whole-lot lottery decided by the number of applicants**, so the actual per-application allotment
ratio ≈ **k / retail_sub**, where **k = average lots per retail application (≥ 1)**. Since k ≥ 1,
`1/retail_sub` is a **conservative lower bound** — it *under-states* real odds, more so the more
applicants bid multiple lots.

### Back-check against real basis-of-allotment lottery ratios

Using **actual** published retail lottery ratios (allottees ÷ applicants), **not** the circular
`1/subscription` figure most aggregators quote:

| IPO | retail_sub | proxy `1/retail_sub` | **actual** allotment | actual ÷ proxy (k) | gap |
|---|---|---|---|---|---|
| Tata Technologies (2023) | 16.5× | 6.1% | **12.0%** (10 of 83) | 1.99 | +6.0 pp |
| Bajaj Housing Finance (2024) | 7.04× | 14.2% | **20.0%** (≈1 in 5) | 1.41 | +5.8 pp |
| | | | | **mean k ≈ 1.70** | |

**Finding: the proxy under-states actual retail allotment odds by ~1.4–2.0× (mean ≈ 1.7×)** — fully
consistent with the analytical `k/retail_sub` (avg ~1.7 lots per application). It is directionally
right and the correct order of magnitude, but it is **not** an exact allotment ratio.

**Per operator instruction, the formula was NOT tuned to close this gap.** The honest response is to
label the figure as an **estimate/approximation** in the UI (done) rather than fit a fudge factor to
two data points. (A `k` multiplier could be added later if a larger, authoritative fixture supports
a stable value — but two points don't justify baking in a constant.)

### Coverage is thin — and why

The fixture (`tests/fixtures/retail_allotment_ratios.json`) has **2 authoritative points**.
Authoritative per-IPO retail lottery ratios live in registrar/exchange **basis-of-allotment**
documents (Chittorgarh, NSE PDFs) that are **not cleanly machine-sourceable** here (Cloudflare 403 /
connection resets), and most free sources **circularly** quote the allotment ratio *as*
`1/subscription` — which would make the proxy validate itself and is deliberately excluded.

**To expand it (recommended before over-trusting the ~1.7× factor):** pull `retail_sub`, retail
**applications**, and retail **allottees** for ~6–10 mainboard IPOs from **IPOMatrix's
basis-of-allotment tab** (the operator has access — those tables carry applications & allottees per
category), add them as fixture rows, and re-run `tests/unit/test_allotment.py`. The finding above is
analytically grounded (k ≥ 1 ⇒ proxy is a lower bound), so more data will *quantify* k, not overturn
the direction.

## Tests

- `tests/unit/test_allotment.py` — formula properties (undersubscribed → full; oversubscribed →
  reciprocal; `None`/non-positive → `None`; monotonic, bounded) + a **back-check that reports the
  gap** (asserts only loose direction/magnitude — proxy under-states within ~3× — never a tight
  tolerance the formula was fitted to).
- `tests/integration/test_api.py::test_ipo_detail_is_enriched_and_consistent` — the odds ride the
  `/ipo/{id}` detail path and equal `min(1, 1/retail_sub)`; the verdict stays byte-for-byte `/verdict`.

## Status

BUILD-track item; validated (correctness back-check, honest gap reported). Branch
`a3-allotment-ev` — **paused for review before any merge** (Part I-B). No calibration impact.
