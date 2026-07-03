# Enhancement Re-calibration Gate — OFS / Valuation / Anchor

*The same burden of proof GMP got ([GMP_GATE.md](GMP_GATE.md)): each feature is scored **with vs
without** on the same IPOs, walk-forward out-of-sample, the **calibrator refit per arm** (never
bolted onto the official-only calibrator with prior weights), reporting ECE + AUC and a
paired-bootstrap CI on the AUC lift, across several walk-forward splits. Gated **separately** per
feature so a brittle field (valuation) cannot contaminate a clean one (OFS). Data is a **Chittorgarh
research pull** (operator-directed, one-time, rate-limited; **not** a sanctioned ongoing source),
mapped to the 293 OOS-eligible official-NSE IPOs. Engineering/research reference — not financial
advice. Reproduce: `research/backfill_enhancement.py` then `research/run_enhancement_gate.py`
(moved to `research/` — dead code, **excluded from the build**; see `research/README.md`).*

## Verdicts

| Feature | Verdict | One line |
|---|---|---|
| **OFS** (`ofs_fraction`) | **CUT — not earned** | No AUC lift, calibration slightly *worse*; and as a kill-flag the sign is **backwards** (high-OFS issues listed *better*). |
| **Relative valuation** (`issue_pe ÷ peer_median_pe`) | **NOT EARNED** (CUT on the hand-QA'd subset) | Its apparent calibration benefit on loose data **evaporates** under strict peer-P/E QA; lift CI always includes zero. |
| **Anchor quality** (`anchor_quality`) | **NOT TESTED — data-limited** | The per-investor anchor book (needed for the marquee-fraction composite) is API-rendered on Chittorgarh, not cleanly extractable. Deferred. |

**Net:** none of the three earns a place in the shipped model on this data. All stay out (GMP-parity
outcome). This is consistent with the design thesis (Deep Dive #3): the model is subscription-led
(QIB), and the brakes/confirmation features are largely **redundant with QIB**.

### ⚠️ Two findings that contradict the blueprint's assumptions

1. **The OFS kill-flag is BACKWARDS on our data.** The blueprint assumed high OFS (promoter exit) ⇒
   more listing losses. The opposite holds: near-total-OFS loss rate **17%** vs pure-fresh **26%**
   (table below) — high-OFS issues (big established firms) list *better*. **A naive "OFS → SKIP"
   flag would hurt. Do not implement it.**
2. **Valuation's apparent lift was an outlier artifact.** On the loose 147 it looked
   calibration-helpful; on the hand-QA'd trustworthy 93 it *worsened* ECE. **This is the concrete
   case for why data-QA *before* the gate is essential** — an outlier-dominated peer median
   manufactured a signal that evaporated once the junk was removed.

---

## Backfill coverage (of 293 OOS-eligible mainboard IPOs)

Every IPO resolved to its Chittorgarh page and was **name-verified** (0 mismatches — no false joins).

| Field | Populated | Notes |
|---|---|---|
| `ofs_fraction` | **293 / 293** | Clean: fresh/OFS/total in a structured table; pure-OFS = 1.0, pure-fresh = 0.0. |
| `issue_pe` (post-issue) | 171 / 293 | The rest are loss-making / blank post-issue P/E ⇒ `None` (neutral-with-flag). |
| `peer_median_pe` | 184 / 293 | Peer table has ≥1 positive-P/E peer (issuer row excluded). |
| `relative_valuation` (loose clean) | 147 / 293 | Both a post-issue P/E and a peer median present. |
| `relative_valuation` (**trustworthy**, hand-QA'd) | **93 / 293** | After sanity bounds (below). This is the subset the valuation gate uses. |

### Valuation hand-QA (peer P/E is brittle — Deep Dive #2)

A hand-check of a sample against the source peer tables found real failure modes, so the "clean" 147
were tightened to a **trustworthy 93** under defensible sanity bounds — nothing forced, absences
flagged:

- **peer P/E comparator must sit in [5, 80]** (outside that the "peer" is a bad-earnings-year
  artifact, not a valuation anchor) **and ≥ 2 surviving peers**;
- **issuer post-issue P/E in [3, 120]** (excludes loss-maker artifacts).

Of the 147: **93 trustworthy**, **28** single-peer (median off one peer — dropped), **18**
issuer-P/E out of range (loss-maker artifacts — dropped), **8** all-peers-out-of-bounds (dropped).
Examples correctly dropped: *Gandhar Oil* (relval 0.03 — peer median 209, dominated by chemical
peers at P/E 500–800), *Zinka/BlackBuck* (loss-maker with a spurious post-P/E), *Shadowfax* (P/E 170).

---

## OFS — CUT (N = 293, base rate 70%)

As a **score feature** (the `−0.05 × ofs_fraction` brake), refit per arm:

| split (initial/step) | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 175/58 | 118 | cut | 0.815→0.820 | 0.071→0.086 | +0.005 [−0.020, +0.035] |
| 146/43 | 147 | cut | 0.829→0.828 | 0.066→0.074 | −0.001 [−0.022, +0.020] |
| 117/29 | 176 | cut | 0.817→0.818 | 0.085→0.092 | +0.001 [−0.017, +0.021] |

AUC is unmoved; ECE is consistently a touch **worse**; the lift CI straddles zero on every split.

As a **kill-flag / loss-avoidance signal**, the blueprint's thesis (high OFS = promoter exit = more
listing losses) is **not supported — the sign is backwards**:

| OFS bucket | N | listing-loss rate (gross, vs band top) |
|---|---|---|
| OFS = 0 (pure fresh) | 34 | 26% |
| 0 < OFS ≤ 0.5 | 103 | 30% |
| 0.5 < OFS ≤ 0.9 | 86 | 23% |
| **OFS > 0.9 (near-total)** | 70 | **17%** (lowest) |

Near-total-OFS issues (typically large, established firms) listed *better*, not worse. OFS earns its
place **neither** as a score feature **nor** as a kill-flag on this data.

---

## Relative valuation — NOT EARNED (trustworthy N = 93, base rate 66%)

On the hand-QA'd trustworthy subset, refit per arm:

| split (initial/step) | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 55/18 | 38 | cut | 0.858→0.878 | 0.119→0.142 | +0.020 [−0.000, +0.055] |
| 46/13 | 47 | cut | 0.875→0.876 | 0.119→0.124 | +0.002 [−0.040, +0.042] |
| 37/9 | 56 | cut | 0.900→0.893 | 0.116→0.142 | −0.007 [−0.044, +0.021] |

**The data-quality caution is the headline.** On the *loose* 147, valuation *improved* ECE and
"kept" on all splits (a promising read) — but that benefit **evaporates on the trustworthy 93**,
where it *worsens* ECE. In other words, the apparent lift was partly an artifact of outlier-dominated
peer medians, exactly the risk the hand-QA was meant to catch. The AUC-lift CI includes zero
throughout. N = 93 is enough to say **"not proven,"** not enough to prove a small effect if one
exists — so this is **NOT EARNED**, with the honest note that valuation's is the *least-unpromising*
of the three (orthogonal price signal) and the most data-quality-sensitive. Revisit only with a
cleaner, larger peer-P/E source.

---

## Anchor — NOT TESTED (data-limited)

`anchor_quality` is a 0–1 composite of **marquee-anchor fraction** (vs a curated recognized list),
value-weighted **lock-in**, and full placement (Deep Dive #2). The IPO main pages carry only the
anchor *total* (₹), not the per-investor book; the per-IPO anchor-investor list is **API-rendered**
on Chittorgarh and not cleanly extractable from the static/JSON pages (unlike OFS and peers). A
faithful anchor gate therefore needs a separate anchor-data source. Deferred.

**v2 roadmap entry:** *Anchor not tested — the anchor-investor list is API-rendered on Chittorgarh,
not cleanly sourceable. Strong prior it is QIB-redundant like OFS / valuation / GMP (the blueprint
calls marquee anchors and strong QIB "the same sentiment twice", Deep Dive #3), so an "EARNED"
outcome is unlikely and the brittle scrape isn't worth it now. Revisit only if a clean anchor source
becomes available.* Given OFS and valuation (the latter with a *better* theoretical claim) both
failed on redundancy, this is a deliberate stop, not an oversight.

---

## Boundaries (do not over-read)

- **Hot-market-heavy, small N.** Base rates ~66–70%; OOS blocks are 38–176. Same statistical wall
  GMP hit — a real effect this small may be unprovable here.
- **Single source** (Chittorgarh RHP-derived), **research pull only** — not a sanctioned ongoing
  feed; there is no live source for these fields (see [SHIPPED_APP_GAPS.md](SHIPPED_APP_GAPS.md) #4).
- **GMP-parity methodology.** Features enter at their fixed config weights and the *calibrator* is
  refit per arm; this does **not** fit per-feature coefficients (that would be a different model).
- **Point-in-time safe:** these are static issue characteristics (known at/before close), so no
  as-of leakage — the concern is signal, not timing.

## Outcome — weights zeroed, shipped calibrator untouched

`ofs_fraction`, `relative_valuation`, and `anchor_quality` scorer weights are set to **0.0** in
`config/default.yaml` (exactly as `market_regime` was), so that if their backfilled data is ever
wired into live features it **cannot silently inject a now-disproven contribution** into the
calibrated score. The shipped QIB-led calibrator (`models/calibrator.json`) is **unchanged** — the
weights just go to 0 for the dead features.

**Byte-for-byte confirmation** (same guard used for `market_regime`): with all three features
**populated** (real OFS on 293, real valuation on 147, a synthetic marquee anchor on all) but at
weight 0, the walk-forward OOS probabilities are **identical** to the current shipped model:

```
MAX |Δscore| = 0.000e+00      (shipped official-only vs populated-at-weight-0)
MAX |Δprob|  = 0.000e+00      (walk-forward 175/58: 118 OOS · 146/43: 147 OOS)
```

They provably cannot move the number. Revisit any of the three only via a fresh re-calibration gate
on cleaner/larger data — never by wiring a live feed.

**Code quarantine.** The backfill/extraction adapters (OFS extraction, peer-P/E parsing, RHP
scraping, NSE↔Chittorgarh joins) live in **`research/`**, which is **excluded from the build** — the
shipped artifact bundles only `src/ipo/` (PyInstaller `collect_submodules("ipo")`) + the PWA, so
this code structurally *cannot* be packaged, wired up, or run in production. The inert scorer slots
(`ofs_fraction` / `relative_valuation` / `anchor_quality`, weight 0, like `market_regime`) stay in
`src/` and ship harmlessly. Marker: *failed re-calibration gate (2026-07-03, hot N=293); retained in
`research/` for a possible v2 re-test; excluded from build; do NOT ship or wire live without
re-running the gate.*
