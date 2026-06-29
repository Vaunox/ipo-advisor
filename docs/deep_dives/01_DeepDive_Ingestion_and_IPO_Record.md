# Deep Dive #1 — Ingestion & the IPO Record

*Source connectivity, the canonical IPO record, the supervised label, and the polite-scraper contract for the Indian IPO listing-gains advisor. This is the foundation; every wrong field here is silently inherited by every feature, score, and calibration downstream. Grounded June 2026.*

---

## Why this layer comes first

The model is only ever as honest as the record it scores. Two failure modes dominate here, both silent:

1. **Wrong-as-of values.** A field is captured at the wrong time — final subscription instead of the closing figure as of the decision, or a GMP read after listing. The record looks complete; it is time-poisoned.
2. **Silent source drift.** An aggregator changes its HTML or a field's meaning, the parser keeps returning *something*, and the something is wrong. The system never errors; it just degrades.

The architecture makes both loud: every parse validates against a schema and **fails on mismatch**, and every field carries the timestamp at which it was true.

---

## Module 0 — The source map (what each source actually gives)

| Field group | Primary source | Notes / gotchas |
|---|---|---|
| **Listing-day open/close (the LABEL)** | NSE / BSE listing data | The supervised target. Capture both open and close. Some issues list on one exchange only. |
| **Final subscription (QIB / NII / retail)** | NSE / BSE subscription pages; Chittorgarh aggregates | NII splits **sNII / bNII** (post-2022). Capture the **closing** figures as the as-of value. |
| **Day-by-day subscription** | NSE intraday (live), trackers historically | Needed for the as-of clock during the bidding window; historically patchy. |
| **Issue structure (fresh vs OFS, size, price band, lot)** | SEBI RHP / DRHP; Chittorgarh | OFS fraction is a feature; price band top normalizes GMP. |
| **Peer-comparison table (issue P/E + peer P/E)** | RHP (SEBI-mandated section) | The relative-valuation input. **Some issues declare "no listed peers"** — handle explicitly (Deep Dive #2). |
| **Anchor allotment (names, amount, lock-in)** | Exchange anchor-investor disclosure (filed pre-listing) | Feeds the anchor-quality score. |
| **Promoter litigation / risk factors** | RHP risk-factor section | Feeds a kill-flag; parse conservatively. |
| **Mainboard vs SME flag** | Exchange listing segment | **Critical filter** — SME is excluded/penalized upstream. |
| **GMP (current + history)** | Grey-market trackers | Deferred to Phase 5 / Deep Dive #5 — unofficial, noisy, separate. |
| **Market regime (Nifty trend/vol)** | NSE / Yahoo Finance | Index series at the expected listing date. |

**Chittorgarh is the convenient aggregator** (most fields in one place) but it is *not* authoritative — treat it as a fast path and **verify subscription + listing figures against NSE/BSE** before they enter a label or a backtest. Never let one aggregator be both source and check.

---

## Module 1 — The canonical IPO record

One typed record per IPO, every field timestamped, raw provenance retained:

```python
@dataclass
class IPORecord:
    ipo_id: str                 # stable key (ISIN once available, else slug)
    name: str
    segment: str                # "mainboard" | "sme"
    price_band_low: float
    price_band_high: float
    lot_size: int
    issue_size_cr: float
    ofs_fraction: float | None  # 0..1
    open_date: date
    close_date: date            # the as-of anchor for decision-time features
    listing_date: date | None
    # subscription (closing, as of close_date EOD)
    qib_sub: float | None
    nii_sub: float | None
    retail_sub: float | None
    # valuation / structure
    issue_pe: float | None
    peer_median_pe: float | None   # None if "no listed peers" declared
    anchor_book: list[AnchorAllotment] | None
    promoter_litigation: bool
    # label (filled post-listing)
    listing_open: float | None
    listing_close: float | None
    # provenance
    captured_at: datetime
    source_hashes: dict[str, str]  # raw-response hash per source
```

`ipo_id` is stable across the lifecycle (pre-issue → subscription → listing) so incremental updates never duplicate a row.

---

## Module 2 — The label builder

```
listing_return_open  = (listing_open  - issue_price) / issue_price
listing_return_close = (listing_close - issue_price) / issue_price
```
`issue_price` = price-band top (the cut-off most retail applies at). Edge cases to handle explicitly, each with a test:
- **Withdrawn / deferred issue** → no label; excluded from training, logged.
- **Listing delayed** → label filled when listing data appears, not before.
- **Single-exchange listing** → use whichever exchange listed it; don't null the label.
- **Net-of-cost label** (the one the model predicts) is computed in Deep Dive #4 from this gross return, not here — keep ingestion cost-free and pure.

---

## Module 3 — The polite-scraper contract (non-negotiable)

Nothing outside `data/sources/` knows a source exists; each adapter implements `DataSource`. Every adapter obeys:

- **Schema-validate on parse → fail loud.** If an expected field is missing or off-type, raise — never return a half-record. This is the tripwire for source drift.
- **Cache raw responses immutably**, hashed; parsing is a pure function of the cached raw. Re-parsing never re-fetches.
- **Rate-limit + backoff**, honest `User-Agent`, respect `robots.txt`/ToS, prefer official endpoints over aggregators where both exist.
- **Idempotent upserts** keyed on `ipo_id` — re-running an ingest never duplicates or silently mutates; corrections become new versioned rows.
- **One source's failure ≠ system failure.** A down aggregator degrades that field (→ possibly `INSUFFICIENT_SIGNAL` downstream), it doesn't crash the run.

```python
class DataSource(Protocol):
    def fetch(self, ipo_id: str) -> RawResponse: ...     # cached, hashed
    def parse(self, raw: RawResponse) -> PartialRecord: ...  # pure, schema-validated
```

**Output contract of Layer 1:** a versioned Parquet table of `IPORecord`s (mainboard-tagged, fields timestamped, provenance retained) plus a label table, reproducible on demand and verified against official subscription/listing figures.

---

## Open questions to settle while building

- **`issue_price` convention:** price-band top (recommended, matches retail cut-off) vs discovered cut-off price if different.
- **Aggregator trust:** which fields are taken from Chittorgarh directly vs always cross-checked against NSE/BSE.
- **History depth:** how many past mainboard IPOs to backfill for the Phase 4 calibration sample (target ≥100; more is better but older regimes are less representative).

---

*This is an engineering/research reference, not financial advice. Aggregator data must be verified against official exchange figures before it enters a label or backtest.*
