# Check 2 — cold-market/regime + T+3 stability stress-test for Total-only

*Phase-1 deployability, off-main branch `total-only-gate`. Verification only — shipped calibrator
git-proven byte-identical (`models/calibrator.json` SHA1 `fa2635717bb0179e2b21ed17b5ade4e7d5b25848`
== HEAD). Engineering/research reference, not financial advice. Code: `research/total_only_variant.py`,
`research/run_total_only_regime_check.py`. Run: `PYTHONPATH="src;." python -m
research.run_total_only_regime_check`.*

## Question

The shipped model was stress-tested through cold-market regime lineage (PROJECT_LOG §4.5) and the
T+3 settlement cross-break (§4.6); `total_only` (from the Part-1 gate, `TOTAL_ONLY_GATE.md`) has not.
Does its calibration hold in cold markets and across the settlement cutover the same way the full
model's does, or does it degrade in exactly the conditions where the category split might have
mattered more?

## Method

Reused the **shipped functions directly** — `ipo.calibration.regime.NiftyRegime`,
`ipo.service.stability.cross_break_stability`, `ipo.calibration.reliability.evaluate_reliability` —
against the `total_only` arm's walk-forward OOS probabilities from Part 1, at the default 60/20
walk-forward (the same window §4.1/§4.5/§4.6 report on). Regime is classified at **listing date**
(cold ≡ Nifty negative 3-month trend or drawdown), matching §4.5's convention exactly.

**Harness validation (required before trusting the total_only numbers):** the `full` model run
through this same harness reproduces the committed PROJECT_LOG numbers exactly:

| check | committed (§4.5/§4.6) | this harness (full, control) | match |
|---|---|---|---|
| Regime All | 298 / 70% / 0.80 / 0.081 | 298 / 70% / 0.80 / 0.081 | ✅ exact |
| Regime Hot | 193 / 75% / 0.80 / 0.077 | 193 / 75% / 0.80 / 0.077 | ✅ exact |
| Regime Cold | 105 / 60% / 0.76 / 0.102 | 105 / 60% / 0.76 / 0.102 | ✅ exact |
| T+3 pre | n=117, base 73%, ECE 0.134 | n=117, base 73%, ECE 0.134 | ✅ exact |
| T+3 post | n=181, base 68%, ECE 0.075 | n=181, base 68%, ECE 0.075 | ✅ exact |
| T+3 ECE shift | −0.060 | −0.060 | ✅ exact |

## Results

### Regime stress-test (§4.5-style)

| model | Regime | N | Base | AUC | ECE | APPLY N | APPLY prec (95% CI) |
|---|---|---|---|---|---|---|---|
| **full** | All | 298 | 70% | 0.80 | 0.081 | 191 | 85% [79%, 89%] |
| **full** | Hot | 193 | 75% | 0.80 | 0.077 | 143 | 85% [79%, 90%] |
| **full** | Cold | 105 | 60% | 0.76 | 0.102 | 48 | 83% [70%, 91%] |
| **total_only** | All | 298 | 70% | 0.81 | 0.079 | 181 | 85% [79%, 90%] |
| **total_only** | Hot | 193 | 75% | 0.81 | 0.084 | 139 | 86% [79%, 90%] |
| **total_only** | Cold | 105 | 60% | 0.77 | **0.133** | 42 | 83% [69%, 92%] |

### T+3 settlement cross-break stability (§4.6-style)

| model | slice | n | base rate | ECE | APPLY precision |
|---|---|---|---|---|---|
| **full** | pre-T+3 (< 2023-12-01) | 117 | 73% | 0.134 | 87% (n=70) |
| **full** | post-T+3 (≥ 2023-12-01) | 181 | 68% | 0.075 | 83% (n=121) |
| **total_only** | pre-T+3 (< 2023-12-01) | 117 | 73% | 0.131 | 87% (n=68) |
| **total_only** | post-T+3 (≥ 2023-12-01) | 181 | 68% | 0.070 | 84% (n=113) |

ECE shift: full **−0.060**, total_only **−0.062** — both flagged DIFFERENCE (tolerance 0.030), both
for the **same already-documented reason** (§4.6): the pre-cutover slice is composition-driven (the
2017-extension's +65 IPOs are all pre-2021, a colder era), not a genuine settlement-change effect.
Nothing new here — total_only inherits the exact same explanation, not a new problem.

## Honest read

**Ranking/selection edge: holds, in every regime.** AUC is the same or fractionally *better* for
total_only across All/Hot/Cold (0.81/0.81/0.77 vs full's 0.80/0.80/0.76) — consistent with the Part-1
gate finding that total_only's ranking tracks the full model even more tightly than QIB-only does.
APPLY precision in the cold slice is statistically indistinguishable (83% vs 83%, heavily overlapping
CIs [69%,92%] vs [70%,91%]) — the actionable selection behavior in a cold market is unchanged.

**Calibration: comparable in All/Hot, meaningfully worse in Cold — the one real finding.**
Total_only's Cold ECE is **0.133 vs full's 0.102** — both already exceed the model's own 0.10
calibration tolerance (the full model's cold-calibration weakness is a documented, accepted
limitation, §4.5b: "flag, don't force"), but total_only's is about **30% relatively worse** in the
coldest slice specifically. All/Hot ECE are within noise of full (0.079/0.084 vs 0.081/0.077).

**A secondary, smaller behavioral shift:** total_only issues fewer APPLY verdicts overall (181 vs
191, ~5% fewer) — its calibrated probability crosses the 0.65 cutoff slightly less often, concentrated
in the cold slice (42 vs 48 APPLYs). A marginally more conservative model in cold conditions, not a
precision problem (precision is unchanged).

## Verdict

**Total-only passes the regime/T+3 stress-test with one specific, non-disqualifying caveat.**

- Ranking/discrimination is fully preserved in every regime, including cold — the model's core value
  (selecting winners) transfers cleanly.
- T+3 cross-break behavior is identical in kind and magnitude to the full model's, for the same
  understood (composition, not settlement) reason.
- Calibration in cold markets is somewhat worse than the full model's own already-marginal cold
  calibration. This is a real degradation, not noise — but it is a **known failure mode class** the
  shipped model already manages by design (regime flag "cold market — probability less certain",
  weight-0, flag-don't-force, §4.5b), not a new one total_only introduces. A total_only deployment
  would need that same cold-market caveat treatment, applied a touch more conservatively given the
  larger cold-ECE gap.

**Consequence for the deployability write-up (Check 3):** total_only is not just viable in the
all-regime aggregate (Part 1) — it holds up under the same stress tests the shipped model had to
pass, with the cold-calibration caveat as the one honest asterisk. Combined with Check 1 (Upstox
closed as a source; NSE/BSE-direct recommended), the technical case for a total_only public model is
now stress-tested end-to-end, pending the sourcing decision.
