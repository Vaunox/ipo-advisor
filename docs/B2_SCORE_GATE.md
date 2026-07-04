# B2 second half — India VIX as a score feature (gate)

*The B2 flag-enrichment half already shipped (VIX into the cold flag at weight 0). This gates the **score-feature** half: VIX entered as a weighted input, scored WITH vs WITHOUT on the same IPOs, walk-forward OOS, **calibrator refit per arm** (GMP-parity — a fixed prior weight, not a fitted coefficient), ECE + AUC + a paired-bootstrap CI on the AUC lift across ≥3 splits. Null hypothesis: **QIB-redundancy** (fear already echoes through cautious QIB bidding); the burden of proof is on the feature. Expanded 2017–2026 sample. Engineering/research reference — not financial advice.*

## India VIX (vol-stress at close) as a score feature — **CUT**

> India VIX (vol-stress at close) as a score feature does not improve (or degrades) the model on any split — not earned.

- Clean-coverage N: **358** · base rate 68% · APPLY precision @ 0.65: off 85% (N=89) vs on 86% (N=90)

| split (initial/step) | OOS N | gate | AUC off→on | ECE off→on | AUC lift (95% CI) |
|---|---|---|---|---|---|
| 214/71 | 144 | cut | 0.827→0.823 | 0.055→0.058 | -0.005 [-0.025, +0.018] |
| 179/53 | 179 | cut | 0.826→0.826 | 0.060→0.074 | +0.000 [-0.016, +0.019] |
| 143/35 | 215 | cut | 0.834→0.832 | 0.060→0.068 | -0.002 [-0.017, +0.012] |
