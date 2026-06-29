# Regime Replication — independent skworld Kaggle sample (2010+, cold-richer)

*Independent check, NOT mixed into the official calibrator (different label: gross listing gain net of ~0.5% cost). Same subscription-only model + walk-forward + regime segmentation. Question: does 'cold calibration degrades' replicate on more cold data? Not financial advice.*

OOS IPOs: **546** | cold: **214** | hot: **332** | deep-cold 2011–13: **54**

| Regime | N | Base | AUC | ECE | APPLY prec | 95% CI |
|---|---|---|---|---|---|---|
| All | 546 | 67% | 0.81 | 0.074 | 84% (N=331) | [79%, 87%] |
| Hot | 332 | 73% | 0.85 | 0.085 | 86% (N=234) | [81%, 90%] |
| Cold (neg 3m trend/drawdown) | 214 | 58% | 0.73 | 0.083 | 78% (N=97) | [69%, 85%] |
| Deep-cold 2011–2013 | 54 | 57% | 0.50 | 0.118 | 67% (N=12) | [39%, 86%] |

## Reading

Compare the **Cold ECE** here against the official-only result (cold ECE ~0.10–0.14, over the 0.10 tolerance). If cold ECE is similarly high on this larger, independent, cold-rich sample, the regime-dependence of the *probability* is a real, replicated finding — reinforcing the gate/flag decision, not a small-sample fluke. If cold ECE is fine here, our cold degradation was likely a thin-sample artifact. The *ranking* (AUC, APPLY vs base) is the apples-to-apples check; the absolute probability differs because the label definition differs.