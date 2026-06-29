# Deep Dive #5 — GMP History (the scraper)

*Reconstructing a usable historical grey-market-premium series from unofficial, disagreeing sources — the messiest data problem in the system, and deliberately the last data work, done only after the official-data model already calibrates. Grounded June 2026.*

---

## The problem, stated honestly

GMP is the model's most heavily-weighted feature and its least trustworthy data. It is an **over-the-counter, informal market with no electronic order book, no clearinghouse, and no SEBI oversight** — so there is no authoritative archive to pull from. Consequences you must design around:

- **No official history.** You reconstruct a series by scraping trackers that each source their own dealer network.
- **Sources disagree.** Chittorgarh, IPOWatch, IPO360, investorgain, and mainboardgmp can quote different GMPs for the same IPO on the same day.
- **It's noisy and gameable.** GMP can be inflated then dumped; a high opening GMP that fades is a known manipulation pattern (and a kill-flag, Deep Dive #3).
- **It is directional, not precise.** Historically GMP *direction* matches listing direction ~70–75% of the time; the magnitude is often well off. Build it to inform the sign, never to predict the exact pop.

This is why GMP is Phase 5: the system must already work and calibrate on clean official data first, so GMP has to *earn* its place by improving calibration, not be assumed load-bearing.

---

## Module A — Per-IPO reconstruction

For each historical IPO, scrape a **day-by-day GMP series** across the bidding window from one primary source plus one fallback, align on date, and store a per-IPO time series. From that series the feature layer needs only two as-of values:

- **GMP level at subscription close** (`gmp_pct`)
- **GMP slope over the final two days** (`gmp_slope_pct`)

Both must be the values *as of the close date* — never a later or listing-day GMP (that would leak; see Deep Dive #4 §B). Trackers that show "GMP live rates day by day" (e.g. per-IPO history tables) are the practical source for the historical series.

```python
class GMPHistory(Protocol):
    def series(self, ipo_id: str) -> list[GMPPoint]: ...  # [(date, gmp_value, source)]
```

---

## Module B — Reconciling disagreeing sources

When two sources differ for the same IPO-day:

- Prefer a **median across available sources** for the level (robust to one outlier quote), or a primary-with-fallback rule if only two exist.
- **Flag large divergence** (e.g. sources differ by more than a set band) as a low-confidence point; a window full of low-confidence points should push the record toward `INSUFFICIENT_SIGNAL` rather than a confident GMP feature.
- Record which source produced each point (provenance), so a later source change is auditable.

Never average silently across sources that flatly contradict each other — surface the disagreement as reduced confidence.

---

## Module C — Quality, manipulation, and honesty

- **Winsorize** GMP inputs; a single absurd print shouldn't move a verdict.
- **Detect the spike-then-collapse pattern** and let it feed the GMP-collapse kill-flag, not just the slope feature.
- Treat GMP strictly as a **sentiment proxy**. The model's *confidence* comes from official subscription/anchor/valuation data; GMP contributes mainly to the *sign*. This separation is what keeps the system from becoming a grey-market hype amplifier.

---

## Module D — The re-calibration requirement (the gate for GMP)

Adding GMP is not assumed to help — it must be *shown* to help:

1. Reconstruct GMP series for the Phase 4 IPO sample.
2. Wire GMP into the feature layer.
3. **Re-run the full Phase 4 calibration** with GMP included.
4. Compare reliability (ECE/Brier) and APPLY-precision **with vs without** GMP on the untouched outer blocks.

GMP stays in **only if the recalibrated model is at least as well-calibrated** as the official-only model. If the noisy series degrades calibration, it comes out — a striking but legitimate outcome given GMP's noise.

---

## Legal / operational caution

Grey-market activity is informal and unregulated; this system uses GMP for **informational scoring only** and never facilitates grey-market trading. Scrape unofficial trackers politely (rate-limit, cache, honor ToS/robots) and treat their data as best-effort. Watch for SEBI's floated **"when-listed" platform**: if it launches, it becomes a regulated, official pre-listing price source — adopt it as the GMP substitute and retire this scraper.

**Output contract of Layer-1-extension (GMP):** a per-IPO GMP time series with provenance and confidence flags, yielding as-of `gmp_pct` and `gmp_slope_pct`, validated by a re-calibration that proves GMP earns its weight.

---

## Open questions to settle while building

- **Primary source vs median:** which trackers to treat as primary; how many to require before trusting a point.
- **Divergence band:** how far apart sources must be before a point is low-confidence.
- **Coverage floor:** minimum days of GMP history within the window before the GMP feature is considered present (else critical-feature-missing → abstain).

---

*This is an engineering/research reference, not financial advice. Grey-market premium is unofficial, unregulated, and not a guarantee of listing price; it is used here only as a noisy directional sentiment signal, gated by calibration.*
