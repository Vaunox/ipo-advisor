# Check 1 — Upstox `total_subscription` field verification

*Phase-1 deployability, off-main branch `total-only-gate`. Verification only — shipped calibrator
git-proven byte-identical (`models/calibrator.json` SHA1 == HEAD). Engineering/research reference,
not financial advice. All code in `research/`.*

## Question

Before trusting total-only as a public-model foundation, confirm that a real licensed source's
`total_subscription` means the **same thing** as our NSE-sourced **final at-close overall multiple** —
same snapshot point, same basis. Source under test: **Upstox** (Analytics Token → IPO API).

## What was done

- Read the **official Upstox Python SDK** model source (public GitHub) for the exact field surface.
- The operator pulled the live IPO list (`GET /v2/ipos`, `status=listed|closed`, `issue_type=regular`,
  paginated) with their own Analytics Token, into a token-free `research/upstox_pull.json`
  (196 mainboard IPOs, 2024-03 → 2026-07). *(The assistant did not run the authenticated call.)*
- `research/compare_upstox_vs_nse.py` joins that pull to our 358-IPO backfill on close date +
  fuzzy name (strict 1:1), and reports per-IPO deltas + agreement buckets.
- Three large **recent** discrepancies were adjudicated against a third source.

## Findings

### 1. Field surface — confirms the premise (with an important scope caveat)
The **licensed developer API** (Analytics Token) exposes exactly **one** subscription number,
`total_subscription`, on both `IpoListingData` and `IpoDetailsData`; the public docs list only two IPO
endpoints (`/v2/ipos`, `/v2/ipos/{id}`), neither with a category breakdown. `issue_type ∈ {regular, sme}`
cleanly separates mainboard from SME.

**Caveat added 2026-07-13 (operator screenshot):** Upstox's **consumer website** *does* show the full
**day-wise QIB/NII/Retail split** (e.g. Kusumgar 08→10-Jul-26, Total 3.47×→13.15×→**128.5×**, with QIB
surging 0.03→0.2→**192.59** on the final day). So the split is **not** absent from Upstox — it is absent
from the *licensed API*, and present only on the *consumer web* (scraping = non-authoritative, same
bucket as Chittorgarh). The authoritative home of the split is **NSE/BSE**, which publish it officially
(our backfill already uses it). Net: "total-only is all that's licensable" holds **only if the source is
a broker's free developer API**; NSE/BSE-direct licensing would provide the full correct split.

The screenshot also **confirms the stale-snapshot diagnosis directly**: Upstox's consumer site shows
Kusumgar's correct final 128.5× (matching the API here), while the day-wise table makes the final-day
institutional surge explicit — exactly the surge the stale API values (Meesho/BCCL/Corona) were missing.
Since Upstox's own website carries the correct final, the developer API's stale `total_subscription` looks
like a **fixable API-side bug**, not a fundamental data gap — a concrete question to put to the vendor.

### 2. Coverage — a hard historical floor
`total_subscription` is populated only from **~2024-11-11 onward**; every IPO before that (and REITs/
InvITs) returns `0.0` (238 of 394 rows). So Upstox is **useless for historical backfill** but fine as
a **go-forward** feed.

### 3. Definitional basis — MATCHES (when the value is final)
Of 118 IPOs present in both sets (1:1, same close date + name), when Upstox carries the final figure
it agrees with ours to a fraction of a percent, Upstox consistently ~0.3% lower (rounding/snapshot):

| bucket | N | within 1% | within 2% | median \|Δ%\| |
|---|---|---|---|---|
| **All matched** | 118 | 61 | 76 | 1.00% |
| **Recent (close ≥ 2025-09)** | 61 | 43 | 51 | 0.57% |
| **Older (close < 2025-09)** | 57 | 18 | 25 | 5.51% |

So the **construct is the same** (total bids ÷ shares offered, overall multiple) — the total-only model
concept transfers.

### 4. Operational data quality — the real problem
A material tail disagrees badly: **36/118 (30%) off by >10%**, and **32/36 are Upstox-LOWER**. The
one-directional understatement is the fingerprint of a **stale pre-close snapshot that missed the
final-day institutional surge** (the same final-day-QIB-surge effect documented in our B1 probe).
It is **worse in the older window** (27/57 off >10%) but **not absent recently** (9/61).

Three recent outliers adjudicated against a third source — **our backfill is right, Upstox is wrong**
in every case:

| IPO (close) | ours | Upstox API | third-source final overall | who's right |
|---|---|---|---|---|
| Meesho (2025-12-05) | 79.03 | 23.33 | **79.03×** (ICICIdirect) | ours ✓ |
| Bharat Coking Coal (2026-01-13) | 146.87 | 98.51 | **146.8×** (NSE, 13-Jan 17:00) | ours ✓ |
| Corona Remedies (2025-12-10) | 137.04 | 35.00 | 134.63× day-3 (Upstox's *own* news)† | ours ✓ |

†Corona has third-source noise (one outlet cited 50.22×), but our value matches Upstox's own news
feed; the Upstox **API** value (35.00) is the outlier.

Because the errors are **idiosyncratic** (ratios range 0.10–0.67, not a constant), **no "close-enough"
adjustment factor can repair them** — this is a data-quality/timing gap, not a fixable basis offset.

### 5. Four-source cross-check on one IPO (Kusumgar, close 2026-07-10) — added 2026-07-13
Operator compared our live app, Groww, Upstox web, and Chittorgarh for the same IPO. Two independent
effects, both quantified:

| source | QIB | NII | Retail | Total | note |
|---|---|---|---|---|---|
| **Ours (live app)** | 284.1 | 165.46 | 26.47 | **128.85** | = IPO Watch final exactly |
| Groww | 284.10 | 164.57 | 24.94 | 127.89 | stamped "as of 4:30 PM" |
| Upstox web | 192.59 | 163.87 | 26.02 | 128.5 | QIB anchor-INCLUDED |
| Chittorgarh | 299.51 | 174.28 | 27.97 | 135.80 | stamped 6:54 PM, QIB "Ex Anchor" |

- **Snapshot timing:** 128.85 (5 PM) → 135.80 (7 PM reconciled) = **+5.4%**; QIB 284.1 → 299.51 = **+5.4%**
  (identical) — the same data ~2 h apart. Our value = the 5 PM close snapshot, corroborated by IPO Watch
  (128.85 to the decimal) and Groww's 4:30 PM read. **Not an error on our end.**
- **QIB divergence, mechanism NOT confirmed (correction, 2026-07-14):** an earlier version of this doc
  claimed Upstox's 192.59 = anchor-*inclusive*-denominator QIB and that folding anchor into the
  77.14L-share QIB portion "explains" 284→192. Checked the arithmetic: anchor (46.29L) is exactly 60% of
  the stated QIB portion (77.15L) — the SEBI anchor-of-QIB cap — so gross/net QIB = 77.15/30.86 = **2.50×**.
  The *observed* ratio is 284.1/192.59 = **1.48×**. These do not match, so that specific mechanism is
  **not** what's happening — the claim was asserted without doing the check and is retracted. The true
  cause is unconfirmed. What stays directly observed (not inferred): QIB diverges 30–56% across sources
  (192/284/300) for the same IPO; NII/Retail (no anchor complication) agree within ~1%. **Practical
  consequence, unaffected by the correction:** Upstox's API schema (`IpoDetailsData`/`IpoListingData`,
  checked against the SDK) has **no anchor field of any kind** — so even a confirmed formula could not be
  inverted per-IPO from API data alone. A QIB "conversion factor" from Upstox is not viable, full stop,
  independent of what the actual mechanism turns out to be.

**Consequence:** for one IPO, "QIB subscription" legitimately spans **192 → 284 → 300** depending on anchor
convention + snapshot; the **total** is far more stable (three sources within 0.75% at the same snapshot).
This is an **independent argument for total-only** beyond licensing: the split isn't merely unlicensable,
it is not even unambiguously *defined* across sources, so a QIB-based live model risks a silent
train/serve skew from anchor-convention mismatch.

**Pipeline convention check (resolved 2026-07-13, code-traced):** backfill and live are **convention-
consistent** — both source subscription from the *same* NSE `ipo-active-category` endpoint, "Total" row
(`noOfTotalMeant`): backfill `nse.subscription(symbol)` (cached, run_backfill.py:82), live
`subscription(symbol, force=True)` (live.py:63). The store is last-write-wins (repository.py:70/86) and a
just-closed issue stays in `ipo-current-issue` until it *lists*, so every refresh in that multi-day window
re-pulls and overwrites subscription — live converges to NSE's settled value (= what a later backfill query
returns). So our Kusumgar 128.85 is NSE's own `ipo-active-category` "Total" (= IPO Watch exactly); Chittorgarh's
135.80 is external aggregator variance, **not** a pipeline defect. **Residual low-prob risk:** `resolve_listings`
never re-pulls subscription (live.py:134-143), so if NSE dropped an issue from `ipo-current-issue` before any
post-close refresh ran, a pre-final snapshot would freeze. Optional future hardening (touches shipped `live.py`,
out of scope for this verification branch): one `subscription(force=True)` re-pull at listing-resolution.

### 6. Re-confirm — does the DETAILS endpoint fix the staleness? NO (2026-07-14)
Both `/v2/ipos` (list) and `/v2/ipos/{id}` (details) schemas carry the identically-named
`total_subscription` field (confirmed against the SDK model in §1). Operator ran
`research/fetch_upstox_details.py` against 10 known-stale "suspects" (Meesho, BCCL, Corona, Swiggy,
Vishal Mega Mart, Sanathan, DAM Capital, Transrail, Enviro Infra, Senores) + 5 clean "controls"
(Kusumgar, CMR Green, Turtlemint, Rubicon, Lenskart).

**Result: `details_total == list_total` for all 15/15, to full float precision** (e.g. Swiggy
`1.5145264993714966` matches digit-for-digit on both endpoints). This is the same cached value served
by both endpoints, not an independently-fresher read. **The details endpoint does not fix the
staleness** — confirmed, not merely suspected. Upstox's `total_subscription` (both endpoints) is a
single stale-prone field with no fresher alternative anywhere in the licensed API surface.

### 7. Control — is OUR backfill CSV itself stale (cache risk)? NO, confirmed live (2026-07-14)
`RawCache` (base.py) is write-once-immutable — a cached response is never overwritten. The backfill
script's `nse.subscription(symbol)` call defaults to `force=False`, i.e. reads the cache if present.
That's a legitimate structural risk: if a symbol's subscription was cached *before* NSE's own number
fully settled, our CSV could be frozen on a stale value too, which would undermine the "ours is right"
conclusion in §4. Tested directly: `research/fetch_nse_fresh.py` re-fetched all 10 suspects + 4 controls
from NSE's public `ipo-active-category` endpoint **live, with `force=True` (cache fully bypassed)** —
public, unauthenticated data, no token, same endpoint the shipped backfill/live pipeline already scrapes.

**Result: 14/14 exact matches, fresh-NSE-right-now == our backfill CSV, to the cent**, spanning IPOs
14+ months old (Swiggy, closed 2024-11-08) to 2 months old (CMR Green). NSE's own subscription figure is
genuinely settled and stable — it is not a matter of "our cache froze an early read." The Upstox gap is
Upstox's own data quality, confirmed independently of any caching concern on our side:

| symbol | fresh NSE (now) | our CSV | Upstox |
|---|---|---|---|
| MEESHO | 79.03 | 79.03 | 23.33 |
| BHARATCOAL | 146.87 | 146.87 | 98.51 |
| CORONA | 137.04 | 137.04 | 35.00 |
| SWIGGY | 3.59 | 3.59 | 1.51 |
| VMM | 27.28 | 27.28 | 2.83 |

### 8. Operator hypothesis — is staleness confined to pre-API-launch data? PARTIALLY, NOT CLEANLY (2026-07-14)
Upstox's IPO API has an announced effective launch date of **2026-05-23**. Hypothesis: maybe errors
are a clean pre/post-launch split (old backfilled data stale, anything captured after launch correct)
rather than randomly jumbled.

**Test 1 — strict launch-date split** on the existing 118 matched pairs: only **2** matches fall on/
after 2026-05-23 (both clean) — far too thin (N=2) to test anything, and the pre-launch matches show
badly-wrong entries (BCCL −32.9%, Clean Max −14.1%, Innovision −25.1%) scattered within *weeks* of the
launch date, disproving a clean cutover at that boundary.

**Test 2 — extend N** by fetching fresh NSE (`force=True`, cache bypassed, public/no-token) for 8
mainboard Upstox rows closing after 2026-05-23 that aren't yet in our static CSV. Combined post-launch
N=10:

| symbol | close date | fresh NSE | Upstox | pct off |
|---|---|---|---|---|
| CMR Green | 2026-06-05 | 127.04 | 126.73 | −0.2% |
| Turtlemint | 2026-06-23 | 1.20 | 1.19 | −1.0% |
| Laser Power | 2026-07-13 | 38.94 | 38.73 | −0.5% |
| Kusumgar | 2026-07-10 | 128.85 | 128.50 | −0.3% |
| Knack Packaging | 2026-07-03 | 83.33 | 82.98 | −0.4% |
| **Aastha Spintex** | 2026-07-01 | 4.64 | 6.80 | **+46.5%** |
| CSM Technologies | 2026-06-29 | 1.36 | 1.34 | −1.4% |
| Advit Jewels | 2026-06-25 | 212.63 | 211.40 | −0.6% |
| **Waterways Leisure** | 2026-06-25 | 1.67 | 1.45 | **−13.1%** |
| Hexagon Nutrition | 2026-06-09 | 53.68 | 52.91 | −1.4% |

**8/10 clean, 2/10 genuinely wrong — entirely after the announced launch date.** This directly
falsifies the strict form of the hypothesis ("after release, data is correct"). Aastha Spintex is
also a **new failure direction**: Upstox is too *high* by 46.5%, the opposite of every earlier
stale-snapshot case (which were all Upstox-*low*) — ruling out "a single early-snapshot mechanism"
as the complete explanation; something else (data mix-up, a different bug) is also present.

**What does hold, with a caveat:** 80% clean post-launch beats the ~64% clean rate across the *full*
pre-launch set — but this is **not specifically about the API launch**. The already-established
"recent" bucket (close ≥ 2025-09-01, **months before the API existed**) was already 83.6% clean
(§3-4). The improvement tracks **general recency**, not a launch-date step-function — Upstox's data
gets fresher the closer to "now," launch or no launch, and appears to have a durable ~15-20% failure
floor even at the freshest edge tested.

**Verdict on the hypothesis:** partially right in spirit (fresher-closing IPOs tend to be cleaner)
but wrong in mechanism (no clean launch-date cutover) and wrong in completeness (a 1-in-5 failure
rate persists at the freshest edge, in both directions). Does not change the Check 1 verdict — Upstox
is still not safely usable without an external cross-check, even for the newest IPOs.

## Verdict

**Not disqualifying as a *concept* (total-only is sound and definition-matched), but Upstox
specifically is confirmed NOT deployable as the source — the staleness is endpoint-wide with no
in-API fix, not a one-off snapshot-timing artifact.**

- ✅ **Definition/basis**: identical to ours → the total-only foundation is legitimate on a
  correctly-measured total multiple.
- ✅ **Mainboard filtering**: `issue_type=regular` works.
- ⛔ **Snapshot/timing — confirmed unfixable in-API (§6)**: Upstox's captured value is frequently **not**
  the final at-close figure — ~15% of recent IPOs (and ~half of older ones) are frozen at an earlier,
  **understated** reading, and Upstox does **not** retroactively correct them (long-listed IPOs still show
  stale values in a 2026-07 pull). Tried the obvious in-API fix — the details endpoint (`/v2/ipos/{id}`) —
  and it returns the **identical cached value** as the list endpoint for all 15 IPOs tested (stale and
  clean alike, matched to full float precision). There is no other subscription-bearing endpoint in the
  documented API. **This is not a "call it differently" problem — it is a data-quality defect in the one
  field Upstox exposes**, with no workaround inside the API surface itself.
- ⛔ **No adjustment factor** — errors are per-IPO, not a constant (confirmed independently in §5's QIB
  analysis too: even where a mechanism seems plausible, e.g. an anchor-related convention, the arithmetic
  doesn't reproduce a fixed ratio — there is no clean multiplier to apply).

**Deployment implication — revised:** Upstox's licensed API cannot be trusted as a standalone source for
`total_subscription`, full stop — not "with a caveat," since the one in-API escape hatch (details vs
list) was tested and closed. A public model would need an **external** cross-check (NSE/BSE final, or a
second independent tracker) with a staleness/sanity guard before trusting any Upstox subscription value —
at which point Upstox is providing convenience/UX, not the authoritative number. Absent that cross-check,
~15% of verdicts would be built on an understated subscription and would wrongly downgrade strong IPOs
(errors are one-directional-low, confirmed non-fixable by endpoint choice).

## Scoping consequence for Check 2

Since **no adjustment factor is viable**, Check 2 should stress-test the total-only model on our
**clean NSE final** total_sub (the definitional foundation), *not* on Upstox's raw values. The
Upstox data-quality issue is a separate **deployment-plumbing** requirement that carries into the
Check 3 verdict — it is not a reason to gate a deliberately-degraded input.
