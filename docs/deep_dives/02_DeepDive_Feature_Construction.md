# Deep Dive #2 — Feature Construction

*How each raw field becomes a model input — the construction recipes, the normalization philosophy, and the missing-data policy that drives abstention. Point-in-time correctness (the as-of clock and the leakage suite) is specified in Deep Dive #4 §B; this document is about *what* each feature is and *how* it is computed. Grounded June 2026.*

---

## The feature set (and what each is for)

Eight features, each a **pure function of data known at the decision time** (subscription close). They divide into a *direction* group (GMP, subscription, anchors) and a *brake* group (valuation, OFS) plus *context* (regime):

| Feature | Drives | Sign |
|---|---|---|
| GMP level | direction (dominant) | + |
| GMP final-days slope | direction (momentum) | +/− |
| QIB subscription | confidence (institutional) | + |
| NII subscription | confidence | + |
| Retail subscription | confidence (weak) | + |
| Anchor quality | confidence | + |
| Relative valuation | brake (over-pricing caps the pop) | − |
| OFS fraction | brake (promoter exit) | − |
| Market regime | context | +/− |

The model leans on the *confidence* group for how sure it is, and on GMP for the *sign* — never the reverse (GMP is unofficial; see Deep Dive #5).

---

## Construction recipes

**GMP level.** `gmp_pct = gmp_value / price_band_high * 100`, taken as the last grey-market quote at or before the close date. Normalize with a saturating map (diminishing returns past ~25%) so a 60% GMP doesn't dwarf everything.

**GMP final-days slope.** Change in `gmp_pct` over the final two days of the bidding window. **Direction matters as much as level** — a GMP of +20% that *rose* from +10% is healthier than +20% that *fell* from +35%. Clamp to a bounded range; a sharp negative slope also triggers a kill-flag (Deep Dive #3).

**Subscription (QIB / NII / retail).** Each is an oversubscription multiple; apply a saturating transform (40× and 80× both signal "very strong" — the difference is noise). QIB carries the highest weight because it is the institutional valuation verdict revealed with real money; retail the lowest (retail chases GMP, so it partly echoes a feature you already have).

**Anchor quality (0–1).** A composite, not a single number:
- fraction of the anchor book allotted to **recognized institutional anchors** (maintain the recognized-anchor list in config — top domestic MFs, insurers, sovereign/pension funds — *do not hardcode names in code*);
- **lock-in length** (longer = more conviction);
- whether the anchor book was **fully placed**.
Combine into 0–1. Missing anchor data → feature is `None` (see missing-data policy), not 0.

**Relative valuation.** `valuation_vs_peers = issue_pe / peer_median_pe`. 1.0 = in line (neutral); >1 = pricey (negative contribution). **The "no listed peers" case is real** (e.g. first-mover issues): when the RHP declares no comparable listed peer, `peer_median_pe` is `None` → the valuation feature is **neutral-with-a-flag**, and the reason string notes "no listed peer to anchor valuation" rather than silently scoring it.

**OFS fraction.** Straight from issue structure (0..1). Near-total OFS also trips a kill-flag.

**Market regime.** A −1..+1 composite at the **expected listing date**: e.g. Nifty 20-day trend (sign + magnitude) blended with a volatility read (India VIX or realized vol). Hot, low-vol tapes lift listings; stressed tapes compress them. Keep the blend weights in config.

---

## Normalization philosophy

- **Saturating maps** for unbounded positives (GMP, subscription) — `1 - exp(-x/scale)` — so extremes compress rather than dominate.
- **Winsorize** raw inputs at sensible caps before transform so one bad scraped print can't swing a verdict.
- **No cross-IPO standardization at score time.** Unlike the cross-sectional equity system, each IPO is scored on its *own* absolute signals (you're deciding about one issue, not ranking a universe). The calibrator (Deep Dive #4) handles turning the combined score into a comparable probability.

---

## The missing-data policy (this is where abstention is born)

Classify each feature as **critical** or **optional**:
- **Critical:** GMP level and QIB subscription. Either missing (or the book not yet closed) → the engine returns `INSUFFICIENT_SIGNAL`. It does **not** guess.
- **Optional:** anchors, peer valuation, regime, NII/retail. Missing → that contribution is dropped (treated neutral) and the reason string says so, but the verdict still computes.

This single policy is what makes "the system abstains when blind" enforceable rather than aspirational. A record with a missing critical feature must never produce a probability.

**Output contract of Layer 2:** `build_features(record, asof) → IPOFeatures`, point-in-time by construction, with explicit `None`s for missing fields (never silent zeros), leakage tests green (Deep Dive #4 §B).

---

## Open questions to settle while building

- **Anchor-quality weights:** how to weight marquee-fraction vs lock-in vs full-placement; tune alongside the model in Phase 4.
- **Regime composite:** trend/vol blend and lookback window.
- **Peerless valuation:** neutral-with-flag (recommended) vs treating "no peer" as a mild negative (often a sign of aggressive pricing).
- **GMP scale constant:** the saturation scale that best separates outcomes — fit empirically in Phase 4, don't guess.

---

*This is an engineering/research reference, not financial advice. Grey-market premium is unofficial data; it sets direction, not certainty.*
