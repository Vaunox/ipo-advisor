"""GMP level-only screening test on the nikhilraj Kaggle set (replication lane only).

NOT the Phase-5 answer. Independent dataset, its own (gross, open-based) label, never
fed to our calibrator. The one question it can address: does **GMP level add discrimination
incremental to subscription demand** (AUC of subscription-only vs subscription + GMP,
walk-forward OOS, paired-bootstrap CI on the lift)?

Hard limits, stated in the report:
* This set has only a single *total* subscription column — not QIB. Baseline = total
  subscription (a demand proxy), not QIB.
* Its single GMP value is almost certainly **final/near-listing** (corr with listing ~0.92),
  i.e. LEAKY — so any lift is **optimistically biased** (upper bound, not the as-of-close truth).
* No day-by-day data → tests NOTHING about GMP slope or the GMP-collapse kill-flag.
* Window 2020–2023 is hot-market-skewed → says little about cold regimes.

Reads the CSV from a local path (gitignored); only the derived report is committed.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from ipo.calibration.reliability import auc_score

_REPO_ROOT = Path(__file__).resolve().parents[1]
_COST = 0.5  # ~0.5% round-trip cost; positive label if listing % exceeds it


def _fit_logistic(
    x: NDArray[np.float64], y: NDArray[np.float64], iters: int = 60
) -> NDArray[np.float64]:
    """Ridge-stabilized Newton logistic fit; X includes an intercept column."""
    beta = np.zeros(x.shape[1])
    ridge = 1e-4 * np.eye(x.shape[1])
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-(x @ beta)))
        w = np.clip(p * (1.0 - p), 1e-9, None)
        grad = x.T @ (p - y)
        hess = x.T @ (x * w[:, None]) + ridge
        try:
            beta = beta - np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            break
    return beta


def _walk_forward_auc(
    feats: NDArray[np.float64], labels: NDArray[np.float64], *, initial: int, step: int
) -> tuple[list[float], list[int]]:
    """Walk-forward OOS predicted probabilities for a logistic on ``feats`` (+intercept)."""
    probs: list[float] = []
    idx: list[int] = []
    start = initial
    n = len(labels)
    while start < n:
        tr = slice(0, start)
        te = slice(start, min(start + step, n))
        mu = feats[tr].mean(axis=0)
        sd = feats[tr].std(axis=0)
        sd[sd == 0] = 1.0
        xtr = np.column_stack([np.ones(start), (feats[tr] - mu) / sd])
        beta = _fit_logistic(xtr, labels[tr])
        xte = np.column_stack([np.ones(te.stop - te.start), (feats[te] - mu) / sd])
        p = 1.0 / (1.0 + np.exp(-(xte @ beta)))
        probs.extend(p.tolist())
        idx.extend(range(te.start, te.stop))
        start += step
    return probs, idx


def main() -> None:
    """Run the level-only GMP screening test and write the report."""
    parser = argparse.ArgumentParser(description="GMP level-only screening (nikhilraj).")
    parser.add_argument("--csv", default="data_store/_kag2/Mainline IPO GMP Performance.csv")
    parser.add_argument("--out", default="docs/GMP_SCREEN.md")
    args = parser.parse_args()

    path = _REPO_ROOT / args.csv
    if not path.is_file():
        raise SystemExit(f"nikhilraj CSV not found at {args.csv}")

    rows = []
    for r in csv.DictReader(path.open(encoding="utf-8", errors="replace")):
        try:
            day = datetime.strptime(r["Listing Date"], "%d-%m-%Y")
            sub = float(r["Subscription"])
            gmp_pct = float(r["Estimated Percentage"])  # GMP as % of issue price
            listing = float(r["Listing Percentage"])
        except (KeyError, ValueError):
            continue
        rows.append((day, sub, gmp_pct, 1 if listing > _COST else 0))
    rows.sort(key=lambda t: t[0])

    sub_log = np.array([np.log1p(r[1]) for r in rows])  # heavy-tailed -> log
    gmp_arr = np.array([r[2] for r in rows])
    y = np.array([float(r[3]) for r in rows])
    n = len(y)

    initial, step = 60, 15
    probs_a, idx_a = _walk_forward_auc(sub_log[:, None], y, initial=initial, step=step)
    probs_b, idx_b = _walk_forward_auc(
        np.column_stack([sub_log, gmp_arr]), y, initial=initial, step=step
    )
    ya = y[idx_a]
    auc_a = auc_score(probs_a, [int(v) for v in ya])
    auc_b = auc_score(probs_b, [int(v) for v in y[idx_b]])

    # Paired bootstrap CI on the marginal lift (same resampled indices for A and B).
    rng = np.random.default_rng(17)
    pa, pb, yy = np.array(probs_a), np.array(probs_b), ya
    diffs = []
    for _ in range(2000):
        s = rng.integers(0, len(yy), len(yy))
        if len(set(yy[s].tolist())) < 2:
            continue
        da = auc_score(pa[s].tolist(), [int(v) for v in yy[s]])
        db = auc_score(pb[s].tolist(), [int(v) for v in yy[s]])
        diffs.append(db - da)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    lift = auc_b - auc_a

    lines = _report(n, len(yy), auc_a, auc_b, lift, float(lo), float(hi))
    (_REPO_ROOT / args.out).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))  # noqa: T201


def _report(
    n: int, n_oos: int, auc_a: float, auc_b: float, lift: float, lo: float, hi: float
) -> list[str]:
    sig = "does NOT" if lo <= 0.0 <= hi else "does"
    verdict_scraper = (
        "NO — even this optimistic (leaky) level-only GMP adds no clear discrimination over "
        "subscription, so a day-by-day slope scraper is not justified by this evidence."
        if lo <= 0.0
        else "INCONCLUSIVE — a lift appears, but the GMP here is leaky (final/near-listing), so it "
        "is an upper bound, not proof that as-of-close GMP helps. This convenient dataset cannot "
        "settle the Phase-5 question; only a true as-of-close series can."
    )
    return [
        "# GMP Level-Only Screening (nikhilraj Kaggle) — replication lane, NOT the Phase-5 answer",
        "",
        "*Independent dataset, its own gross/open-based label, never fed to our calibrator. "
        "Tests one thing: does GMP **level** add discrimination **incremental to subscription**? "
        "AUC is the apples-to-apples metric (label differs from ours). Not financial advice.*",
        "",
        "## Result (walk-forward OOS)",
        "",
        f"- Dataset: **{n}** IPOs (2020–2023), **{n_oos}** out-of-sample.",
        f"- **AUC, total-subscription alone:** {auc_a:.3f}",
        f"- **AUC, subscription + GMP level:** {auc_b:.3f}",
        f"- **Marginal lift from GMP level:** **{lift:+.3f}** "
        f"(95% paired-bootstrap CI [{lo:+.3f}, {hi:+.3f}]) — GMP **{sig}** add signal "
        "beyond subscription.",
        "",
        "## Provenance & leakage (read this before the number)",
        "",
        "- **Subscription column is TOTAL, not QIB** — baseline is total demand, not QIB "
        "specifically (a clean QIB test would need merging our official data, disallowed here).",
        "- **The single GMP value is almost certainly final/near-listing (LEAKY).** "
        "GMP-implied vs actual listing correlate **~0.92** with **84%** direction match — far "
        "tighter than as-of-close GMP (~70–75% directional, magnitude often off). So any lift "
        "above is an **optimistic upper bound**, not the as-of-close truth.",
        "",
        "## What this test CANNOT answer",
        "",
        "- **Nothing about GMP slope or the GMP-collapse kill-flag** — no day-by-day data here.",
        "- A null result rules out **level-only** GMP, not GMP as a whole.",
        "- The 2020–2023 window is **hot-market-skewed**, so it says little about cold regimes.",
        "",
        "## Verdict — is the full day-by-day slope scraper worth building?",
        "",
        f"**{verdict_scraper}**",
        "",
        "Either way, this convenient level-only dataset does not redefine Phase 5: the Phase-5 "
        "question (does as-of-close GMP level + slope earn its weight by improving calibration) "
        "still requires a real, point-in-time, day-by-day series and the re-calibration gate.",
    ]


if __name__ == "__main__":
    main()
