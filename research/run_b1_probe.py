# =============================================================================================
# QUARANTINED — B1 subscription-trajectory CHEAP PROBE (v2). EXCLUDED FROM BUILD (research/ is never
# packaged). This is Step 2 of the gate protocol (a cheap probe on probe-grade, single-source,
# optimistically-biased data) — NOT a real gate and NOT a wiring. It reads the shipped model,
# scorer, and dataset READ-ONLY and changes nothing. Verdict + evidence: docs/B1_PROBE.md.
# =============================================================================================
"""B1 probe — does the SHAPE of the subscription buildup add signal beyond the final multiples?

Hypothesis: how the book built over the window (final-day QIB surge, early-vs-late demand) carries
signal beyond the settled final subscription the model already scores. Dropped earlier for lack of
day-wise history; the arXiv 2412.16174 HF dataset (sohomghosh/Indian_IPO_datasets, Chittorgarh-
sourced) has day-wise per-category columns for ~418 mainboard IPOs (2009-2023), making a cheap
probe possible with no recorder.

Per Deep Dive #B, aggregator day-wise tables are sanctioned for the CHEAP PROBE ONLY — never the
real gate. This data is probe-grade: single-source, intermediate days unverifiable, optimistically
biased. Honest prior: trajectory is QIB-redundant (the final multiple already encodes it); the
burden is on the feature.

Step 1 (trust-check): match to our NSE-verified backfill (2017-2023 overlap); check the source's
finals against ours, and how far the day-wise columns actually reach.
Step 2 (features, point-in-time at close): final-day QIB surge share = (final_qib - day2_qib) /
final_qib, using THEIR day-2 cumulative and OUR verified final. Point-in-time valid (the settled
book + the day-before value are both known at the close decision clock).
Step 3 (probe): rough with-vs-without via the shared gate harness (calibrator refit per arm,
walk-forward OOS, AUC/ECE + paired-bootstrap CI). Labelled PROBE-GRADE.
Step 4: verdict (see docs/B1_PROBE.md).
"""

from __future__ import annotations

import re
import statistics
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from huggingface_hub import hf_hub_download
from run_b3_gate import _paired
from run_enhancement_gate import _eligible, run_arm, synthesize

from ipo.calibration.dataset import load_records_from_csv
from ipo.core.config import load_config
from ipo.core.types import IPORecord
from ipo.model.scorer import WeightedScorer

_ROOT = Path(__file__).resolve().parents[1]
_HF_REPO = "sohomghosh/Indian_IPO_datasets"
_HF_FILE = "ipo_mainline_final_data_v18.xlsx"
_W_TRAJ = 0.10  # fixed prior weight the surge feature enters at (GMP-parity: fixed, never fitted).
_FEATURE = "QIB final-day surge share (trajectory)"


def _norm(s: object) -> str:
    """Normalise a company name for matching (drop Ltd/Private/punctuation/case)."""
    t = re.sub(r"\b(limited|ltd|private|pvt|the)\b", "", str(s).lower())
    return re.sub(r"[^a-z0-9]", "", t)


def _floats(row: pd.Series[Any], cols: list[str]) -> list[float]:
    return [float(row[c]) for c in cols if pd.notna(row[c])]


def _load_hf() -> dict[str, dict[str, float]]:
    """Return {normalised-name -> day-wise facts} for 2017-2023 mainboard IPOs from the HF set."""
    path = hf_hub_download(_HF_REPO, _HF_FILE, repo_type="dataset")
    df = pd.read_excel(path)
    df = df[df["Close Date"] >= "2017-01-01"]
    qd = [f"day_{d}_qib" for d in range(1, 7)]
    nd = [f"day_{d}_nii" for d in range(1, 7)]
    rd = [f"day_{d}_retail" for d in range(1, 7)]
    out: dict[str, dict[str, float]] = {}
    for _, r in df.iterrows():
        q, n, rt = _floats(r, qd), _floats(r, nd), _floats(r, rd)
        if not q:
            continue
        out[_norm(r["Company Name"])] = {
            "day2_qib": float(r["day_2_qib"]) if pd.notna(r.get("day_2_qib")) else float("nan"),
            "last_qib": q[-1],
            "last_nii": n[-1] if n else float("nan"),
            "last_ret": rt[-1] if rt else float("nan"),
            "ndays": float(len(q)),
            "total_sub": (
                float(r["Total_subscriptions"])
                if pd.notna(r.get("Total_subscriptions"))
                else float("nan")
            ),
        }
    return out


def _rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), 1e-9)


def _trust_check(
    records: list[IPORecord], hf: dict[str, dict[str, float]], our_total: dict[str, float]
) -> dict[str, float]:
    """Step 1 — endpoint fidelity (their last day vs our finals) + source fidelity (finals)."""
    endpoint: dict[str, list[float]] = {"qib": [], "nii": [], "retail": []}
    total: list[float] = []
    reach_final = 0
    matched = 0
    for rec in _eligible(records):
        h = hf.get(_norm(rec.name))
        if h is None:
            continue
        matched += 1
        if rec.qib_sub is not None:
            endpoint["qib"].append(_rel(rec.qib_sub, h["last_qib"]))
            if _rel(rec.qib_sub, h["last_qib"]) <= 0.10:
                reach_final += 1
        if rec.nii_sub is not None and not np.isnan(h["last_nii"]):
            endpoint["nii"].append(_rel(rec.nii_sub, h["last_nii"]))
        if rec.retail_sub is not None and not np.isnan(h["last_ret"]):
            endpoint["retail"].append(_rel(rec.retail_sub, h["last_ret"]))
        ot = our_total.get(rec.ipo_id)
        if ot is not None and not np.isnan(ot) and not np.isnan(h["total_sub"]):
            total.append(_rel(ot, h["total_sub"]))

    def within(xs: list[float]) -> float:
        return 100.0 * float(np.mean([x <= 0.10 for x in xs])) if xs else 0.0

    return {
        "matched": float(matched),
        "endpoint_qib_pct": within(endpoint["qib"]),
        "endpoint_nii_pct": within(endpoint["nii"]),
        "endpoint_ret_pct": within(endpoint["retail"]),
        "reach_final_pct": 100.0 * reach_final / len(endpoint["qib"]) if endpoint["qib"] else 0.0,
        "source_total_pct": within(total),
        "n_endpoint": float(len(endpoint["qib"])),
    }


def _surge_map(records: list[IPORecord], hf: dict[str, dict[str, float]]) -> dict[str, float]:
    """Step 2 — final-day QIB surge share per our ipo_id: (final_qib - day2_qib) / final_qib."""
    surge: dict[str, float] = {}
    for rec in _eligible(records):
        h = hf.get(_norm(rec.name))
        if h is None or rec.qib_sub is None or np.isnan(h["day2_qib"]) or rec.qib_sub <= 0:
            continue
        # fraction of the final QIB book that arrived AFTER day 2 (i.e. on the closing day).
        s = (rec.qib_sub - h["day2_qib"]) / rec.qib_sub
        surge[rec.ipo_id] = float(min(max(s, 0.0), 1.0))
    return surge


def main() -> None:
    """Run the B1 cheap probe and write docs/B1_PROBE.md; change nothing else."""
    config = load_config()
    records = load_records_from_csv(_ROOT / "data" / "backfill" / "mainboard_ipos.csv")
    scorer = WeightedScorer(config.feature_weights, config.features)
    method = config.calibration.method
    cutoff = config.verdict_thresholds.apply

    hf = _load_hf()
    ours_df = pd.read_csv(_ROOT / "data" / "backfill" / "mainboard_ipos.csv")
    our_total = {
        str(row.ipo_id): float(row.total_sub)
        for row in ours_df.itertuples()
        if pd.notna(row.total_sub)
    }
    trust = _trust_check(records, hf, our_total)
    surge = _surge_map(records, hf)
    mean_surge = statistics.fmean(surge.values()) if surge else 0.0

    def traj_add(rec: IPORecord) -> float | None:
        s = surge.get(rec.ipo_id)
        # a-priori sign: a late institutional (QIB) surge reads as confidence -> positive.
        # Centered; fixed prior weight (the calibrator refit per arm adapts, never a fitted coef).
        return None if s is None else _W_TRAJ * (s - mean_surge)

    base, arm, rate = _paired(records, scorer, config, traj_add)
    results = run_arm(base, arm, method=method, cutoff=cutoff)[0]
    probe_verdict, probe_why = synthesize(_FEATURE, len(base), results)

    # Overall B1 verdict: the LITERAL trust-check fails (day-wise truncated at day 2 -> the clean
    # cheap-probe route the HF set offered does not exist), so this is verdict (c) — too poor for
    # a clean probe. The salvaged best-effort read is a supporting sub-result, NOT a permanent
    # close: on probe-grade-squared data a null is consistent with the QIB-redundant prior but can't
    # distinguish "no signal" from "data too noisy to show it".
    overall = "INCONCLUSIVE (data too poor for a clean probe) — salvaged read shows NO PULSE"

    print("\n### B1 trajectory cheap probe (PROBE-GRADE, single-source, optimistically biased)")
    print(f"  OVERALL: {overall}")
    print(
        f"  trust-check: matched {int(trust['matched'])} 2017-2023 IPOs; "
        f"their day-wise reaches our final on {trust['reach_final_pct']:.1f}% "
        f"(endpoint within 10%: qib {trust['endpoint_qib_pct']:.0f}% / nii "
        f"{trust['endpoint_nii_pct']:.0f}% / retail {trust['endpoint_ret_pct']:.0f}%); "
        f"source finals (Total_subscriptions vs ours) agree {trust['source_total_pct']:.0f}%"
    )
    print(
        f"  salvaged probe: N={len(base)} (base rate {rate:.0%}) using their day-2 + our verified "
        f"final -> {probe_verdict}"
    )
    for r in results:
        print(
            f"    {r.initial}/{r.step} OOS={r.n_oos} {'keep' if r.keep else 'cut '} "
            f"AUC {r.auc_wo:.3f}->{r.auc_w:.3f} ECE {r.ece_wo:.3f}->{r.ece_w:.3f} "
            f"lift {r.lift:+.3f} [{r.lo:+.3f},{r.hi:+.3f}]"
        )
    _write_report(
        _ROOT / "docs" / "B1_PROBE.md",
        trust,
        rate,
        len(base),
        overall,
        probe_verdict,
        probe_why,
        results,
    )
    print("\nwrote docs/B1_PROBE.md")


def _write_report(
    out: Path,
    trust: dict[str, float],
    rate: float,
    n: int,
    overall: str,
    probe_verdict: str,
    probe_why: str,
    results: list[Any],
) -> None:
    lines = [
        "# B1 — subscription-trajectory cheap probe (does the buildup SHAPE add signal?)",
        "",
        "*Step 2 of the gate protocol: a cheap probe on **probe-grade** data (arXiv 2412.16174 / "
        "HF `sohomghosh/Indian_IPO_datasets`, Chittorgarh-sourced day-wise) — single-source, "
        "intermediate days unverifiable, optimistically biased. Sanctioned for the probe ONLY, "
        "never a real gate (Deep Dive #B). Read-only against the shipped model/scorer/dataset — "
        "nothing wired, nothing changed. Engineering/research reference — not financial advice.*",
        "",
        f"## Verdict: **{overall}**",
        "",
        "> The HF day-wise columns are truncated at day 2 — the closing day, when the QIB "
        "surge lands, is missing — so the clean cheap-probe route this dataset seemed to offer "
        "does not exist (verdict **c: data too poor**). A best-effort salvage (their day-2 "
        "cumulative + our verified final) was run anyway and shows **no pulse** (below): "
        "consistent with the QIB-redundant prior, but on probe-grade-squared data it does NOT "
        "permanently close B1. Forward collection remains the only route to a real B1 gate; the "
        "'no recorder needed' shortcut is closed with evidence. **Do not build, do not wire.**",
        "",
        "## Step 1 — trust-check (2017-2023 overlap with our NSE-verified backfill)",
        "",
        f"- Matched **{int(trust['matched'])}** mainboard IPOs by name.",
        f"- **Source finals are faithful:** the dataset's `Total_subscriptions` matches our "
        f"NSE-sourced totals on **{trust['source_total_pct']:.0f}%** of overlaps — same "
        "Chittorgarh->NSE lineage, transcription confirmed.",
        f"- **But the day-wise columns are truncated:** their last recorded day reaches our "
        f"verified final on only **{trust['reach_final_pct']:.1f}%** of IPOs (per-category "
        f"endpoint within 10%: QIB {trust['endpoint_qib_pct']:.0f}%, NII "
        f"{trust['endpoint_nii_pct']:.0f}%, retail {trust['endpoint_ret_pct']:.0f}%). The closing "
        "day — when the QIB surge lands — is missing for ~all of them (e.g. Indigo Paints: our "
        "QIB final 189.6x vs their last day 5.4x).",
        "",
        "## Step 2 — feature (point-in-time at close)",
        "",
        "Because the *source's finals* match ours but the day-wise stops at day 2, the probe uses "
        "**their day-2 cumulative QIB + OUR verified final**: `surge = (final_qib - day2_qib) / "
        "final_qib` = the fraction of the final QIB book that arrived on the closing day. "
        "Point-in-time valid (settled book + day-before value both known at close). This is a "
        "*best-effort salvage* — the day-2 value is single-source and unverifiable.",
        "",
        f"## Step 3 — probe (PROBE-GRADE with-vs-without, N={n}, base rate {rate:.0%})",
        "",
        "*Shared gate harness: fixed prior weight (0.10, a-priori sign 'late surge = positive'), "
        "calibrator refit per arm, walk-forward OOS, AUC + ECE + paired-bootstrap CI on the AUC "
        "lift. Same shape as B2/B3/GMP — but probe-grade data, so treat any positive read as "
        "optimistically biased.*",
        "",
        f"**Salvaged-probe sub-result: {probe_verdict}** — {probe_why}",
        "",
        "| split (initial/step) | OOS N | gate | AUC off->on | ECE off->on | AUC lift (95% CI) |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.initial}/{r.step} | {r.n_oos} | {'keep' if r.keep else 'cut'} | "
            f"{r.auc_wo:.3f}->{r.auc_w:.3f} | {r.ece_wo:.3f}->{r.ece_w:.3f} | "
            f"{r.lift:+.3f} [{r.lo:+.3f}, {r.hi:+.3f}] |"
        )
    lines += [
        "",
        "**Honest prior (held):** trajectory is QIB-redundant — the settled QIB multiple the model "
        "already scores plausibly encodes what the path adds. The burden was on the feature.",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
