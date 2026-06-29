# Deep Dive — The Calibration & Backtest Layer

*The layer that turns a score into a **trustworthy probability** and an earned **verdict** for the Indian IPO listing-gains advisor. This is the load-bearing piece: the entire promise of the system is "grounded, confident probability," and that promise lives or dies here. Grounded June 2026.*

---

## Why this layer is the one that quietly breaks everything

A scoring model has two separate virtues, and people conflate them:

- **Discrimination** — can the score *rank* IPOs, putting the eventual winners above the losers? Measured by AUC / rank correlation.
- **Calibration** — when the model says **70%**, does the thing happen ~70% of the time? Measured by reliability diagrams, Brier score, ECE.

A model can rank perfectly and still emit garbage probabilities (e.g. every winner gets 0.55, every loser 0.45 — perfect ranking, useless numbers). For this product the **calibrated number is the deliverable**, so discrimination is necessary but not sufficient. The placeholder logistic squash in `ipo_advisor.py` discriminates a little and is calibrated not at all — which is exactly why it printed a 99%. Replacing it is non-optional.

Three failure modes kill calibration silently — the system runs, prints confident numbers, and the numbers lie:

1. **As-of leakage.** A feature uses a value known only *after* the decision — final-day GMP when you decided at subscription close, or (worst) the listing return itself bleeding into an input. Backtest looks brilliant; live is a coin flip.
2. **Overfitting a tiny sample.** Tuning weights *and* thresholds *and* the calibrator on the same ~100 IPOs you then evaluate on inflates every metric. With a sample this small the temptation is acute.
3. **Regime dependence.** Listing-gain base rates swing hard with the cycle. A calibrator fit on a hot 2024 is miscalibrated on a cold tape. A single random shuffle hides this; only time-ordered evaluation exposes it.

The architecture below makes all three *structurally hard to commit*.

---

## Module A — The label (define "positive listing" precisely)

The supervised target is the listing-day outcome of the flip:

```
listing_return = (exit_price − issue_price) / issue_price
positive       = net_of_cost(listing_return) > 0
```

Decisions to lock before fitting anything:
- **Exit price = listing-day open**, not close — the strategy is a listing-day flip, so the open is the honest exit. (Optionally also model a close exit as a second label; do not silently mix them.)
- **Net of cost, not gross.** Subtract the listing-day sell cost (STT 0.1% on sell, the flat ₹15.34/ISIN DP charge, exchange+GST) so a +0.5% "gain" that the costs eat is correctly labelled a loss. The user keeps net, so the model predicts net.
- **One label definition, versioned.** Changing it later invalidates the calibrator; record it with the calibrator artifact.

---

## Module B — As-of snapshot reconstruction (the leakage firewall)

For every historical IPO, reconstruct the feature vector **as it stood at the decision time** — end of the subscription-close day — never the final pre-listing values:

```python
def asof_features(ipo: IPORecord, asof: datetime) -> IPOFeatures:
    """Point-in-time: every field uses only data timestamped <= asof.
    GMP = last quote at/before asof; subscription = closing figures as of asof;
    anchor/RHP/valuation = pre-issue (known before bidding opens).
    The listing return (label) is NEVER read here."""
```

The CI leakage suite (shared with the Feature layer) must assert: no feature reads a post-listing field; the label never appears as an input; and a deliberately-leaky feature (e.g. one that peeks at listing price) makes the suite **fail**. This is the single most important test in the system.

---

## Module C — Walk-forward split (no random folds, ever)

Sort IPOs by date. Fit on the past, evaluate on the future, roll forward:

```
|—— fit window ——|— eval —|
        |—— fit window ——|— eval —|
                |—— fit window ——|— eval —|
```

Random K-fold leaks future regime into the past and is forbidden. Use a **nested** scheme: an inner split tunes weights + thresholds + the calibrator; the **outer** eval block is touched exactly once, for reporting. The outer block is the only number you are allowed to believe.

---

## Module D — The calibrator (small-sample-honest)

Two standard choices map raw scores → probabilities:
- **Platt / sigmoid scaling** — a 2-parameter logistic fit on (score, label). Robust on small samples. **The default here**, given ~100 IPOs.
- **Isotonic regression** — non-parametric, more flexible, but data-hungry and prone to overfit small samples. Switch to it only once you have a few hundred labelled IPOs.

Fit the calibrator on a **held-out calibration fold**, not the fold the scorer was tuned on (the "prefit" pattern) — otherwise it calibrates to memorised noise. Persist it **versioned**, alongside the feature-code hash and the label definition, so a verdict is always reproducible. Weight recent IPOs more (mild time-decay) so the calibrator tracks the current regime rather than averaging across cycles.

Minimal, library-agnostic reliability check (no fragile API dependency):

```python
def reliability(probs, labels, n_bins=10):
    """Returns per-bin (mean_predicted, observed_rate, count) + ECE + Brier."""
    edges = np.linspace(0, 1, n_bins + 1)
    rows, ece = [], 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (probs >= lo) & (probs < hi)
        if not m.any():
            continue
        pred, obs, w = probs[m].mean(), labels[m].mean(), m.mean()
        ece += w * abs(pred - obs)
        rows.append((pred, obs, int(m.sum())))
    brier = float(np.mean((probs - labels) ** 2))
    return rows, ece, brier
```

A reliability diagram plots `pred` vs `obs`; a calibrated model sits on the diagonal.

---

## Module E — Threshold tuning

Choose the `APPLY` / `MARGINAL` cutoffs on the **calibrated probability**, against the operator's objective — most naturally the **precision of APPLY** (of all APPLY verdicts, what fraction actually listed positive net-of-cost), with a floor on how many APPLYs you get. Tune on the inner fold, report on the outer. The cutoff is a product decision, not a fitted parameter — keep it in config.

---

## THE RELIABILITY GATE (set thresholds before running)

The analogue of the equity system's kill-gate. A calibrator ships to users only if **all** pass on the untouched outer blocks:

1. **Discrimination:** OOS AUC meaningfully above 0.5 (the score actually ranks).
2. **Calibration:** ECE below a pre-set bound; the reliability curve sits within a stated band of the diagonal; the 0.6–0.8 predicted bucket lists positive within that range.
3. **Beats base rate:** report the unconditional positive-listing rate over the sample; APPLY precision must clear it by a meaningful margin (else the model adds nothing over "apply to everything").
4. **Time-stable:** calibration holds across at least two distinct time blocks — not carried by one hot window.
5. **Look-ahead test passes:** shuffle the label → discrimination and calibration collapse to chance. If they don't, there is leakage somewhere.
6. **Abstention validated:** `INSUFFICIENT_SIGNAL` cases are excluded from the scored metrics, not silently scored as 0.5.

Fail any → the probability is not shown to users; only the verdict logic with an explicit "uncalibrated — not for decisions" banner is allowed in dev. **No user-facing release before this gate passes.**

---

## The small-sample reality (say it out loud)

~100 mainboard IPOs is enough to fit a 2-parameter sigmoid and check calibration *roughly*, but confidence intervals on every bucket are wide. Don't oversell early numbers. The honest posture: ship the calibrated model, **state the sample size and base rate next to every probability**, recalibrate quarterly and after regime shifts, and widen the sample over time. Mainboard-only keeps the population coherent (SME has a different, manipulated distribution and is excluded upstream).

---

## What I'd build for this layer (concrete spec)

A `calibration/` package:
1. **`backtest.py`** — walk-forward driver over labelled IPOs using `asof_features`; nested inner/outer split; emits per-IPO (score, prob, label, verdict) frames.
2. **`calibrate.py`** — Platt fit on the held-out fold (isotonic switch behind config); persisted, versioned calibrator carrying the feature-hash + label-definition.
3. **`reliability.py`** — the binning above, ECE/Brier, a saved reliability-diagram PNG, and the gate checks as asserts.
4. **A written calibration report** (`docs/CALIBRATION.md`) — sample size, base rate, AUC, ECE, Brier, the diagram, APPLY precision, and the chosen thresholds. This report is the artifact that earns the right to show probabilities.

**Build/validate order:** labels → as-of reconstruction (+ leakage suite green) → walk-forward driver → Platt calibrator on held-out fold → reliability diagram + gate → threshold tuning → report. **Do not wire the calibrator into the scoring core (Layer 3) until the gate passes and the look-ahead test collapses skill to chance.**

---

## Open questions to settle while building

- **Exit definition:** listing-day open (default) vs close — or ship both as separate labels/calibrators.
- **Positive threshold:** net-of-cost > 0, or a small positive buffer to avoid marginal "wins" that aren't worth the bid.
- **Calibrator family:** sigmoid now; at what sample size (a few hundred?) is isotonic justified.
- **Regime handling:** one calibrator with time-decay weighting, vs separate hot/cold-regime calibrators selected by the market-regime feature.

---

*Next companion docs, if useful: the Ingestion deep-dive (source-by-source field map + the polite-scraper contract) and the GMP-history scraper deep-dive (reconstructing a noisy series from disagreeing trackers).*

*This is an engineering/research reference, not financial advice. A calibrated probability is an estimate, not an assurance — a well-calibrated 70% still fails ~30% of the time, and listing-gain base rates vary sharply with the market cycle.*
