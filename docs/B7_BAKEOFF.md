# B7 — model-architecture bake-off: TabPFN v2 vs the logistic core

*Head-to-head on the 358-IPO sample, same walk-forward OOS folds, AUC + ECE with a paired-bootstrap CI on the AUC difference (TabPFN - logistic), across >=3 splits. Both models see the same core subscription features (QIB / NII / retail). **Higher bar:** adopting TabPFN forfeits the grounded reason, so it wins only by beating logistic **decisively** (AUC lift >= 0.03, CI clear of zero every split, ECE no worse) - not on a tie or a marginal edge. Engineering/research reference - not financial advice.*

## Verdict: **LOGISTIC STAYS - TabPFN not decisively better**

> TabPFN does not beat the logistic core by enough to justify forfeiting the grounded reason (the AUC edge is small / its CI includes zero / ECE is not better on some split). The interpretable model explains every verdict ('QIB 42x'); TabPFN is a black box. On this evidence the interpretability outweighs any marginal metric edge -- logistic is retained, the question closed.

- Sample N: **358** · challenger: TabPFN v2 (pretrained tabular transformer) · incumbent: fixed-weight scorer → Platt (the shipped, interpretable core)

| split (initial/step) | OOS N | AUC logistic | AUC TabPFN | ECE logistic | ECE TabPFN | AUC diff (95% CI) |
|---|---|---|---|---|---|---|
| 214/71 | 144 | 0.827 | 0.831 | 0.055 | 0.103 | +0.004 [-0.034, +0.040] |
| 179/53 | 179 | 0.826 | 0.834 | 0.060 | 0.093 | +0.009 [-0.023, +0.040] |
| 143/35 | 215 | 0.834 | 0.852 | 0.060 | 0.080 | +0.018 [-0.008, +0.043] |

**Reading the table.** The largest AUC edge to TabPFN is +0.018 (split 143/35), short of the 0.03 decisive bar; every split's 95% CI includes zero; and ECE is worse for TabPFN on every split. The edge is within noise and comes at a calibration cost -- costly for a calibrated-probability product. Not decisive.

**Operational cost beyond interpretability.** Adopting TabPFN would add a ~29 MB opaque transformer (torch, ~500 MB installed) with vendor telemetry to a self-contained local tool. The current TabPFN line (v2.5 / v2.6 / v3) is gated behind Prior Labs account registration + license acceptance; v2 is ungated today but the trajectory is toward gating. This raises the already-high bar -- it does not lower it.

**Interpretability cost (explicit):** the logistic core explains every verdict from a feature value ('APPLY - QIB 42x'); TabPFN is a black box with no grounded reason. That cost is only worth paying for a decisive, robust accuracy win - which is the bar above.

## Provenance & reproduction

- Challenger pinned to **TabPFN v2** (`ModelVersion.V2`, the ungated public `Prior-Labs/TabPFN-v2-clf` weights) -- the model B7 scoped; the package default now loads the newer `tabpfn_3`.
- Deterministic: `random_state=0`, paired-bootstrap `seed=17` (2000 resamples), CPU.
- Reproduce: `TABPFN_NO_BROWSER=1 .venv/Scripts/python.exe research/run_b7_bakeoff.py`
