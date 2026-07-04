# =============================================================================================
# QUARANTINED — B6 RHP-extraction accuracy probe. EXCLUDED FROM BUILD (research/ is never packaged).
# Validates research/rhp_extract.py against the free HF prospectus dataset; display was NOT wired.
# Evidence: docs/B6_RHP_PROBE.md. Downloads ~141MB to data_store/_rhp/ (gitignored) and caches.
# =============================================================================================
"""B6 probe — how accurately does the RHP extractor read the mandated litigation summary?

Runs ``rhp_extract.extract_rhp_context`` over the free Hugging Face dataset
``scholarly360/indian_ipo_prospectus_data`` (100 real Indian IPO prospectuses) and reports,
honestly: section-detection recall, structured-value coverage, and — for a hand-checked sample —
the precision (does it invent figures?) and recall (does it catch the real ones?) of the
"against the Company" case count and aggregate amount. Auditor-opinion and related-party base
rates are reported too. No ground truth ships with the dataset, so the raw "against the Company"
rows are dumped to ``data_store/_rhp/probe_detail.txt`` for the hand-check behind the report.
"""

from __future__ import annotations

import urllib.request
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq
from rhp_extract import extract_rhp_context

_ROOT = Path(__file__).resolve().parents[1]
_CACHE = _ROOT / "data_store" / "_rhp"
_BASE = "https://huggingface.co/datasets/scholarly360/indian_ipo_prospectus_data/resolve/refs%2Fconvert%2Fparquet/default"
_SPLITS = {"train": f"{_BASE}/train/0000.parquet", "test": f"{_BASE}/test/0000.parquet"}


def _load() -> list[tuple[str, str]]:
    """Download (once) and return [(title, full_text)] across both splits."""
    _CACHE.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, str]] = []
    for split, url in _SPLITS.items():
        dest = _CACHE / f"{split}.parquet"
        if not dest.is_file():
            print(f"downloading {split} ...")  # noqa: T201
            urllib.request.urlretrieve(url, dest)  # noqa: S310
        table = pq.read_table(dest).to_pydict()  # type: ignore[no-untyped-call]
        rows += list(zip(table["title_prospectus"], table["content_whole_prospectus"], strict=True))
    return rows


def main() -> None:
    """Extract over all prospectuses, print coverage metrics, dump rows for the hand-check."""
    rows = _load()
    n = len(rows)
    found = values = disclosed_true = rp_true = 0
    auditor: Counter[str] = Counter()
    detail: list[str] = []
    for title, text in rows:
        ctx = extract_rhp_context(text)
        lit = ctx.litigation
        found += lit.section_found
        values += lit.cases_against_company is not None
        disclosed_true += lit.against_company_disclosed is True
        rp_true += ctx.related_party_disclosed is True
        auditor[ctx.auditor_opinion or "none"] += 1
        if lit.section_found:
            detail.append(
                f"### {title}\n"
                f"parsed: cases={lit.cases_against_company} amount_mn={lit.aggregate_amount_mn} "
                f"disclosed={lit.against_company_disclosed}\n"
                f"row: {lit.source_quote}\n"
            )

    print(f"\n=== B6 RHP extraction probe — N={n} prospectuses ===")  # noqa: T201
    print(f"litigation section detected: {found}/{n} ({found / n:.0%})")  # noqa: T201
    print(  # noqa: T201
        f"structured against-company value extracted: {values}/{n} ({values / n:.0%} of all; "
        f"{values}/{found} of found sections)"
    )
    print(f"  of those, disclosed>0: {disclosed_true}")  # noqa: T201
    print(f"auditor opinion: {dict(auditor)}")  # noqa: T201
    print(
        f"related-party disclosed: {rp_true}/{n} ({rp_true / n:.0%}) — near-constant"
    )  # noqa: T201
    out = _CACHE / "probe_detail.txt"
    out.write_text("\n".join(detail), encoding="utf-8")
    print(f"\nwrote {out} ({found} found-section rows for the hand-check)")  # noqa: T201


if __name__ == "__main__":
    main()
