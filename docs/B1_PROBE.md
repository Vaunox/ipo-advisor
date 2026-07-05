# B1 — subscription-trajectory cheap probe (does the buildup SHAPE add signal?)

*Step 2 of the gate protocol: a cheap probe on **probe-grade** data (arXiv 2412.16174 / HF `sohomghosh/Indian_IPO_datasets`, Chittorgarh-sourced day-wise) — single-source, intermediate days unverifiable, optimistically biased. Sanctioned for the probe ONLY, never a real gate (Deep Dive #B). Read-only against the shipped model/scorer/dataset — nothing wired, nothing changed. Engineering/research reference — not financial advice.*

## Verdict: **INCONCLUSIVE (data too poor for a clean probe) — salvaged read shows NO PULSE**

> The HF day-wise columns are truncated at day 2 — the closing day, when the QIB surge lands, is missing — so the clean cheap-probe route this dataset seemed to offer does not exist (verdict **c: data too poor**). A best-effort salvage (their day-2 cumulative + our verified final) was run anyway and shows **no pulse** (below): consistent with the QIB-redundant prior, but on probe-grade-squared data it does NOT permanently close B1. Forward collection remains the only route to a real B1 gate; the 'no recorder needed' shortcut is closed with evidence. **Do not build, do not wire.**

## Step 1 — trust-check (2017-2023 overlap with our NSE-verified backfill)

- Matched **121** mainboard IPOs by name.
- **Source finals are faithful:** the dataset's `Total_subscriptions` matches our NSE-sourced totals on **98%** of overlaps — same Chittorgarh->NSE lineage, transcription confirmed.
- **But the day-wise columns are truncated:** their last recorded day reaches our verified final on only **0.8%** of IPOs (per-category endpoint within 10%: QIB 1%, NII 2%, retail 2%). The closing day — when the QIB surge lands — is missing for ~all of them (e.g. Indigo Paints: our QIB final 189.6x vs their last day 5.4x).

## Step 2 — feature (point-in-time at close)

Because the *source's finals* match ours but the day-wise stops at day 2, the probe uses **their day-2 cumulative QIB + OUR verified final**: `surge = (final_qib - day2_qib) / final_qib` = the fraction of the final QIB book that arrived on the closing day. Point-in-time valid (settled book + day-before value both known at close). This is a *best-effort salvage* — the day-2 value is single-source and unverifiable.

## Step 3 — probe (PROBE-GRADE with-vs-without, N=120, base rate 69%)

*Shared gate harness: fixed prior weight (0.10, a-priori sign 'late surge = positive'), calibrator refit per arm, walk-forward OOS, AUC + ECE + paired-bootstrap CI on the AUC lift. Same shape as B2/B3/GMP — but probe-grade data, so treat any positive read as optimistically biased.*

**Salvaged-probe sub-result: CUT** — QIB final-day surge share (trajectory) does not improve (or degrades) the model on any split — not earned.

| split (initial/step) | OOS N | gate | AUC off->on | ECE off->on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 72/24 | 48 | cut | 0.794->0.782 | 0.138->0.160 | -0.012 [-0.044, +0.014] |
| 60/18 | 60 | cut | 0.759->0.751 | 0.163->0.172 | -0.007 [-0.037, +0.020] |
| 48/12 | 72 | cut | 0.752->0.753 | 0.165->0.177 | +0.001 [-0.019, +0.021] |

**Honest prior (held):** trajectory is QIB-redundant — the settled QIB multiple the model already scores plausibly encodes what the path adds. The burden was on the feature.
