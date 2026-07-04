# =============================================================================================
# QUARANTINED — B3 deferred-feature gate (pricing-vs-band, BRLM reputation). EXCLUDED FROM BUILD.
# Retained for evidence. Do NOT wire live without re-running the gate and PROMOTING a fitted weight.
# Evidence + verdicts: docs/B3_GATE.md.
# =============================================================================================
"""B3, part 2 — the two features first deferred as data-limited, now sourced and gated.

* **Pricing-vs-band** = final issue price ÷ price-band top (the "voluntary underpricing" channel).
  Sourced from the Chittorgarh pages. Honest prior: mainboard book-builds price the cut-off AT the
  band top, so this is near-constant (little to gate) AND correlates with demand (QIB-redundant).
* **BRLM reputation** — a **point-in-time** league table: each lead manager's market share (Σ issue
  size led) among IPOs that closed *before* this one, averaged over the IPO's managers. Built
  point-in-time, so no look-ahead leaks into the score. Sourced from the Chittorgarh pages
  (lead-manager names) + the enhancement issue sizes.

Same gate as everything else: WITH vs WITHOUT, calibrator refit per arm, ECE + AUC + bootstrap CI,
≥3 splits, honest verdict. Reuses the enhancement harness. Parses pages once (slow) and caches to
``data_store/_enhancement/b3_deferred.json``.
"""

from __future__ import annotations

import csv
import glob
import json
import re
from pathlib import Path
from typing import cast

from bs4 import BeautifulSoup
from run_b3_gate import _paired
from run_enhancement_gate import SplitResult, _ReportRow, run_arm, synthesize

from ipo.calibration.dataset import load_records_from_csv
from ipo.core.config import load_config
from ipo.core.types import IPORecord
from ipo.features.normalize import saturate, signed_saturate

_ROOT = Path(__file__).resolve().parents[1]
_PAGES = _ROOT / "data_store" / "_enhancement" / "pages"
_CACHE = _ROOT / "data_store" / "_enhancement" / "b3_deferred.json"

_W_PRICE = 0.05
_W_BRLM = 0.05


def _norm_brlm(name: str) -> str:
    n = re.sub(r"\b(limited|ltd|pvt|private|co|company|india|the)\b", "", name.lower())
    return re.sub(r"[^a-z0-9]+", "-", n).strip("-")


def _num(text: str) -> float | None:
    m = re.search(r"([\d,]+(?:\.\d+)?)", text or "")
    return float(m.group(1).replace(",", "")) if m else None


def _parse_page(html: str) -> dict[str, object]:
    soup = BeautifulSoup(html, "html.parser")
    kv: dict[str, str] = {}
    for tr in soup.find_all("tr"):
        tds = tr.find_all(["td", "th"])
        if len(tds) >= 2:
            kv.setdefault(tds[0].get_text(" ", strip=True), tds[1].get_text(" ", strip=True))
    band = kv.get("Price Band", "")
    hi = None
    nums = re.findall(r"([\d,]+(?:\.\d+)?)", band)
    if nums:
        hi = float(nums[-1].replace(",", ""))
    final = _num(kv.get("Final Issue Price") or kv.get("Issue Price", ""))
    brlms: list[str] = []
    for head in soup.find_all(re.compile("^h[2-4]$")):
        if re.search(r"lead manager", head.get_text(), re.I):
            box = head.find_next(["ul", "ol", "div", "p", "table"])
            if box:
                for a in box.find_all("a"):
                    t = a.get_text(" ", strip=True)
                    if t and len(t) > 3 and not re.search(r"past ipo|performance", t, re.I):
                        k = _norm_brlm(t)
                        if k and k not in brlms:
                            brlms.append(k)
            break
    return {"band_high": hi, "final_price": final, "brlms": brlms}


def _load_pages() -> dict[str, dict[str, object]]:
    if _CACHE.is_file():
        return cast("dict[str, dict[str, object]]", json.loads(_CACHE.read_text(encoding="utf-8")))
    data: dict[str, dict[str, object]] = {}
    for path in glob.glob(str(_PAGES / "*.html")):
        ipo_id = Path(path).stem
        data[ipo_id] = _parse_page(Path(path).read_text(encoding="utf-8", errors="ignore"))
    _CACHE.write_text(json.dumps(data), encoding="utf-8")
    return data


def _issue_sizes() -> dict[str, float]:
    out: dict[str, float] = {}
    main = _ROOT / "data_store" / "_enhancement" / "enhancement_main.csv"
    for row in csv.DictReader(main.open(encoding="utf-8")):
        raw = str(row.get("total_cr", "")).strip()
        if row.get("status") == "ok" and raw not in ("", "None", "nan"):
            try:
                out[row["ipo_id"]] = float(raw)
            except ValueError:
                pass
    return out


def _brlm_reputation(
    records: list[IPORecord], pages: dict[str, dict[str, object]], sizes: dict[str, float]
) -> dict[str, float]:
    """Point-in-time league table: each IPO's mean lead-manager market share among PRIOR IPOs."""
    ordered = sorted(
        (r for r in records if r.ipo_id in pages and pages[r.ipo_id]["brlms"]),
        key=lambda r: r.close_date,
    )
    cum: dict[str, float] = {}
    total = 0.0
    rep: dict[str, float] = {}
    for rec in ordered:
        brlms = cast("list[str]", pages[rec.ipo_id]["brlms"])
        if total > 0:
            rep[rec.ipo_id] = sum(cum.get(b, 0.0) for b in brlms) / len(brlms) / total
        size = sizes.get(rec.ipo_id, 0.0)
        for b in brlms:
            cum[b] = cum.get(b, 0.0) + size
        total += size
    return rep


def main() -> None:
    config = load_config()
    records = load_records_from_csv(_ROOT / "data" / "backfill" / "mainboard_ipos.csv")
    from ipo.model.scorer import WeightedScorer

    scorer = WeightedScorer(config.feature_weights, config.features)
    method = config.calibration.method
    cutoff = config.verdict_thresholds.apply
    pages = _load_pages()
    sizes = _issue_sizes()

    # --- pricing-vs-band coverage + variation ---
    pvb: dict[str, float] = {}
    for r in records:
        p = pages.get(r.ipo_id)
        if p and p["band_high"] and p["final_price"]:
            pvb[r.ipo_id] = float(p["final_price"]) / float(p["band_high"])  # type: ignore[arg-type]
    below = sum(1 for v in pvb.values() if v < 0.999)
    print(f"pricing-vs-band: N={len(pvb)}  priced below top={below}  at top={len(pvb) - below}")

    rep = _brlm_reputation(records, pages, sizes)
    print(f"BRLM reputation: N={len(rep)} IPOs with point-in-time league-table reputation")

    def price_add(rec: IPORecord) -> float | None:
        v = pvb.get(rec.ipo_id)
        return None if v is None else _W_PRICE * signed_saturate((v - 1.0) / 0.05, 1.0)

    def brlm_add(rec: IPORecord) -> float | None:
        v = rep.get(rec.ipo_id)
        return None if v is None else _W_BRLM * saturate(v, 0.15)

    report: list[_ReportRow] = []
    for name, add_of in [
        ("Pricing-vs-band (cut-off ÷ band top)", price_add),
        ("BRLM reputation (point-in-time league share)", brlm_add),
    ]:
        base, arm, rate = _paired(records, scorer, config, add_of)
        results: list[SplitResult]
        results, prec_wo, prec_w = run_arm(base, arm, method=method, cutoff=cutoff)
        verdict, why = synthesize(name, len(base), results)
        report.append((name, len(base), rate, verdict, why, results, prec_wo, prec_w))
        # Per-split tables are written to docs/B3_GATE.md by _append_report; print the verdict line.
        splits = ", ".join(f"{r.lift:+.3f}[{r.lo:+.3f},{r.hi:+.3f}]" for r in results)
        print(f"\n### {name}: {verdict}  (N={len(base)}, base rate {rate:.0%})  lifts: {splits}")
    _append_report(report, below=below, n_price=len(pvb), n_brlm=len(rep))
    print("\nappended to docs/B3_GATE.md")


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def _append_report(report: list[_ReportRow], *, below: int, n_price: int, n_brlm: int) -> None:
    out = _ROOT / "docs" / "B3_GATE.md"
    lines = [
        "",
        "---",
        "",
        "## Deferred features — sourced from the Chittorgarh pages and gated",
        "",
        f"*Both were first deferred as data-limited; the data was then recovered. Pricing-vs-band: "
        f"final price ÷ band top on **{n_price}** IPOs — **{below}** priced below the top "
        f"(mainboard book-builds price at the cut-off = band top, so near-constant). BRLM "
        f"reputation: a **point-in-time** league table (each manager's market share among "
        f"IPOs that closed earlier), on **{n_brlm}** IPOs — leakage-safe by construction.*",
        "",
    ]
    for name, n, rate, verdict, why, results, prec_wo, prec_w in report:
        lines += [
            f"### {name} — **{verdict}**",
            "",
            f"> {why}",
            "",
            f"- Clean-coverage N: **{n}** · base rate {rate:.0%} · APPLY precision @ 0.65: "
            f"off {_pct(prec_wo[0])} (N={prec_wo[1]}) vs on {_pct(prec_w[0])} (N={prec_w[1]})",
            "",
            "| split (initial/step) | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |",
            "|---|---|---|---|---|---|",
        ]
        for r in results:
            lines.append(
                f"| {r.initial}/{r.step} | {r.n_oos} | {'keep' if r.keep else 'cut'} | "
                f"{r.auc_wo:.3f}→{r.auc_w:.3f} | {r.ece_wo:.3f}→{r.ece_w:.3f} | "
                f"{r.lift:+.3f} [{r.lo:+.3f}, {r.hi:+.3f}] |"
            )
        lines.append("")
    out.write_text(out.read_text(encoding="utf-8") + "\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
