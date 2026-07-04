# B6 RHP-extraction probe — is the mandated-disclosure extraction accurate enough to display?

*Option B only (informational context, no kill-flags, no scoring impact). Before wiring any
detail-page display, prove the extraction against real prospectuses. This is the probe-before-build
gate: if extraction is reliable → wire the context-only display in a follow-up; if it is poor →
keep B6 minimal or drop it, having spent almost nothing. The scorer/verdict/calibrator were **not
touched** — the extractor was pure text extraction, **unwired**, and was never a scoring input.
Engineering/research reference, not financial advice.*

> **Decision (2026-07-04): DROPPED.** On this evidence B6's display was not wired. The extractor was
> **removed from `src/`** (no dead code shipped) and quarantined in `research/` as the tested artifact
> behind the negative. Logged with the other honest negatives in `V2_PROGRESS.md` and the blueprint
> Part III graveyard. The calibrator and the app frontend are byte-for-byte untouched.

**Corpus:** `scholarly360/indian_ipo_prospectus_data` (Hugging Face) — 100 real Indian IPO
prospectuses (full OCR'd text; ~90 unique companies, some repeated across the train/test splits).
Probe + extractor (quarantined in `research/`, never shipped): `research/rhp_probe.py` +
`research/rhp_extract.py`.

## Verdict: extraction is high-precision but far too low-coverage to display the numbers

| Signal | Result | Usable to display? |
|---|---|---|
| Litigation **section detected** | **81 / 100 (81%)** | Partial — a coarse "section present" flag only |
| Structured **litigation count/amount** (against the Company) | **6 / 100 (6%)** extracted; of those, **0 fabricated** — 2 exactly correct (Vedant 22/₹240.53mn, Delhivery 89/₹411.69mn), 1 amount-correct/count-uncertain | **No** — ~7% recall of real disclosures |
| **Auditor opinion** | detected **54 / 100** (emphasis-of-matter 46, qualified 5, unqualified 3) | Maybe — a coarse, unambiguous flag |
| **Related-party disclosed** | **100 / 100 (constant)** | No — every RHP discloses RPTs; zero discrimination |

**Recommendation: do not wire the structured litigation count/amount** — it is honest but only
covers ~6% of prospectuses. The only defensibly-displayable signals are coarse (auditor opinion,
"litigation section disclosed"); related-party is a non-signal. Given B6's whole value was the
mandated litigation figures, the disciplined outcome is **keep minimal (coarse auditor-opinion flag
only) or drop B6** — the probe cost almost nothing and saved a partial, mostly-empty display.

## Recall vs precision on the litigation summary (the field that mattered)

The operator's two questions, answered honestly:

- **Precision — does it invent disclosures? No.** Of the 6 prospectuses where a figure was
  reported, none was fabricated: 2 are exactly right against the source table, 1 has the right
  aggregate amount but a case count that may miss a dropped OCR column. The parser is built to
  **abstain rather than guess** (it requires ≥4 of the 5 mandated count columns to be cleanly
  present, and returns `None` otherwise), so it does not manufacture numbers from noise. Precision
  is high **by construction**.
- **Recall — does it catch the real ones? Rarely (~7%).** All 81 detected sections contain a real
  "outstanding litigation against the Company" disclosure, but a usable figure was parsed from only
  6 of them (~7%). The other ~93% are honestly reported as "not available."

## Root cause — OCR-reflowed tables, not a fixable regex

The mandated *Summary of Outstanding Litigation* (Schedule VI / SEBI Master Circular) is a
fixed-format table, but the dataset's text is **OCR-extracted from PDFs**, and the table columns
reflow unpredictably. The entity label is routinely split from its own row of numbers:

- Vedant (parses correctly): `Against 3 10 5 Nil 4. 240.53 the Company` — label *after* the values.
- Delhivery (parses correctly): `Against the 4 24 13 N.A. 48" 411.69 Company` — label *before*.
- Typical failure: column headers bleed into rows, `N.A.`/`Nil`/`N.AL` spellings vary, footnote
  markers (`48"`, `4.`) and garbled unit words (`lorie` for crore) corrupt the token stream, and
  a column is silently dropped — so ≥4 clean columns can't be recovered and the extractor abstains.

This is a data-quality ceiling (OCR of scanned filings), not a tuning problem. Reliable structured
extraction would need clean source text (e.g. the machine-readable RHP tables or a table-aware PDF
parser), not a better regex over this corpus — and would still leave the live-app text-source
question (deferred) open. That is why the honest read is *coarse-signal-only, or drop*.
