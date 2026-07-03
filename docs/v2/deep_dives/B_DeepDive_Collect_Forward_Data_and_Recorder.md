# Deep Dive #B — Collect-Forward Data & the Recorder

*The data-sourcing detail for v2. Its central theme: **some data can only be collected going forward, so the decision to start collecting is a clock decision, not a build-queue decision.** Every month you don't collect is a month you can't later test the feature that needs it. This deep-dive covers day-wise subscription (for trajectory), the recorder's role, the T+3 cutoffs that bound live polling, and the defensive posture for NSE's fragile endpoints. Grounded July 2026.*

---

## The core principle: collect-forward-or-lose-it

Three kinds of data the model might want are **not reliably archived for free**, so they exist only if you record them from now on:
- **Day-wise subscription buildup** (feeds Track-B trajectory) — official sources publish live figures during the window, but the historical day-by-day path is not cleanly archived.
- **Point-in-time GMP** (feeds the GMP cold re-test, spike-collapse, multi-source confidence) — no historical archive; the recorder's whole reason to exist.
- **Cold-market instances of any of the above** — you only get them as cold markets actually occur.

The consequence is counterintuitive but firm: **you start collecting this data long before you gate the feature that uses it.** Waiting until a feature reaches its turn in the queue means waiting *again* for the data to accrue. So the collection actions (A1 here, the GMP recorder already) run **immediately and in parallel**, decoupled from when their features are tested.

---

## Module B1 — Day-wise subscription banking (Build item A1)

**Goal:** an append-only, timestamped, point-in-time record of how each mainboard IPO's subscription built over its window — the data the trajectory candidate (B1) needs, collected forward starting now.

**Source:** NSE's `ipo-active-category` endpoint (already known to `data/sources/nse.py`), which carries the QIB/NII/sNII/bNII/retail split and an `updateTime`. Poll it through each IPO's open window.

**Cadence:** several times per day during an open book (the final-day QIB surge is the highest-value slice — poll more densely on close day). Off-days with no open IPO: nothing to record.

**Storage contract (append-only, never overwrite):** one row per poll per IPO:
```
ipo_id, symbol, captured_at_ist (ISO8601), qib_sub, nii_sub, snii_sub, bnii_sub,
retail_sub, total_sub, source_updateTime, raw_response_hash
```
Natural key `(ipo_id, captured_at_ist)` for idempotency. The downstream consumer (the trajectory gate) reconstructs the buildup curve and derives velocity/surge-timing features **as-of any point in the window** — so the timestamp is load-bearing and must be honest (the poll time in IST, and the source's own `updateTime`, both retained).

**Why append-only matters:** the whole value over aggregator tables is that *you* know exactly what the number was at each moment. Overwrite a row and you've rebuilt the same untrustworthy, point-in-time-blind data the aggregators already have.

**GATE A1:** day-wise rows land append-only and timestamped for a live IPO; a re-run duplicates nothing; the reconstructed curve for a completed IPO matches the observed progression.

---

## Module B2 — The T+3 regime and its cutoffs (bounds live polling & the EV term)

SEBI circular SEBI/HO/CFD/TPD1/CIR/P/2023/140 moved listing from **T+6 to T+3** (voluntary Sep 1 2023, **mandatory Dec 1 2023**). Two consequences for v2:

1. **Structural break in the training sample.** The 2021+ calibration cohort straddles the cutover, so the close-to-listing decay window *halves* mid-sample. Encode a `t3_regime` dummy with the exact cutover dates and check calibration stability across the break in the next recalibration (Build item A4).
2. **Close-day cutoffs bound live polling and the book-closed cycle.** The circular's annexure fixes issue-close-day cutoffs (UPI ASBA ~4 pm, mandate confirmation ~5 pm on T). This tells the scheduler (A2) **when the book is final** and when the "book closed" scoring cycle should fire — score on the settled book, not a mid-afternoon partial.
3. **EV-layer term.** ASBA funds unblock at T+3, so the allotment-EV layer's blocked-capital opportunity-cost term is ~3 days (A3).

*Verification: the T+3 circular is a primary source (◐ only because the verify panel rate-limited, not because it's doubtful). The close-day cutoff *times* should be confirmed against the annexure text before hard-coding.*

---

## Module B3 — Defensive posture for NSE's internal endpoints

NSE's IPO JSON endpoints (`ipo-active-category`, `all-upcoming-issues`) are **undocumented internal APIs**, not a published contract. They are the authoritative source for the category split — but fragile. Build every adapter on them defensively (the Deep Dive #1 polite-scraper contract, hardened):

- **Session/cookie/UA handshake.** A cold request is usually rejected; hit the NSE homepage first for cookies, carry them, set a browser-like `User-Agent`. Log when the handshake fails.
- **Schema-validate → fail loud.** If the `srNo → category` mapping or any expected field shifts, **raise** — never silently mis-map. An NSE site change must surface immediately, not poison data. There is **no second NSE to corroborate against**, so schema-validation + sanity gates are your only guardrail.
- **Sanity-gate values** — plausible subscription multiples, category mapping intact — and alert on anomalies rather than degrade silently.
- **Cloud-IP hostility.** NSE blocks datacenter IPs aggressively. If ingestion runs anywhere but a residential-ish connection, expect blocking here first; surface it loudly (the recorder-heartbeat model).

Record in `PROGRESS.md` that the confirmed QIB source is NSE's internal endpoint (fragile), not an official stable API — so the ingestion carries the same "treat the source as unreliable, validate, fail loud" discipline as the GMP scraper.

---

## Module B4 — What the recorder covers vs what A1 covers

Two separate collect-forward efforts, both append-only, both forward-only:
- **The GMP recorder** (its own repo, always-on AWS) — banks multi-source, point-in-time GMP. Feeds B4/B5 (GMP cold re-test, spike-collapse, multi-source confidence). Already specified in its own handoff.
- **Day-wise subscription (A1)** — banks the subscription buildup curve from NSE. Feeds B1 (trajectory).

They're distinct data, distinct sources, distinct features — but the same principle governs both: **start now, collect forward, decouple collection from the feature's place in the queue.** Neither can be back-filled from history for free; both accrue value with time.

---

## Aggregator tables — the cheap-probe exception, with the trust boundary

For the *cheap probe* only (Step 2 of the gate), aggregator day-wise tables (e.g. Chittorgarh) may stand in for banked data — a quick read on whether trajectory has any pulse before A1 has accrued enough history. But:
- **Never for the real gate** — aggregator historical day-wise data is unvetted single-source, and (per the trust boundary) label/backtest-critical numbers are cross-checked against official sources, never taken from one aggregator.
- **Treat probe numbers as optimistically biased** — same caution as any cheap-data probe.

The durable path is always A1's banked data. The aggregator is a peek, not a foundation.

---

*Engineering/research reference, not financial advice. Collect-forward data must be append-only and honestly timestamped; NSE's internal endpoints are authoritative-but-fragile and built against defensively.*
