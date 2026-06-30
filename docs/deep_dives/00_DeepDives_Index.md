# Deep-Dive Index — IPO Listing-Gains Advisor

The reference set that backs the **MASTER BLUEPRINT**. Each deep-dive carries the full rationale, recipes, and gotchas for one layer; the blueprint is the distilled build program. Read the relevant deep-dive when a phase needs deeper detail.

| # | Deep dive | Layer | Build phase | What it settles |
|---|---|---|---|---|
| 1 | `01_DeepDive_Ingestion_and_IPO_Record.md` | L1 — Ingestion | Phase 1 | Source map, the canonical `IPORecord`, the label builder, the polite-scraper contract. |
| 2 | `02_DeepDive_Feature_Construction.md` | L2 — Features | Phase 2 | How each raw field becomes a feature; normalization; the missing-data policy that drives abstention. |
| 3 | `03_DeepDive_Scoring_Model.md` | L3 — Scoring core | Phase 3 | Weighted-then-calibrated design, weight philosophy, kill-flags, verdict mapping, reason generator. |
| 4 | `04_DeepDive_Calibration_and_Backtest.md` | L4 — Calibration | Phase 4 | The load-bearing layer: as-of backtest, isotonic/Platt fit, the **reliability gate**. |
| 5 | `05_DeepDive_GMP_History.md` | L1-ext — GMP | Phase 5 | Reconstructing a noisy GMP series from disagreeing sources; the re-calibration gate that makes GMP earn its weight. |
| 6 | `06_DeepDive_Service_and_Packaging.md` | L5 + L6 packaging | Phase 6 (+ Phase-7 packaging) | Scheduler/API/notifier; then the `.exe` packaging — the PyInstaller engine sidecar + the **Electron** shell. The app's UI + Figma design loop are #7. |
| 7 | `07_Phase7_App.md` | L6 — The app | Phase 7 | The Figma design loop + build process; the native Windows `.exe` (**Electron** shell over the engine sidecar) — genuine desktop software; the five inherited UI invariants. |

**Reading order for the build:** blueprint top-to-bottom; open deep-dive *N* at the start of the phase it backs. The scoring skeleton `ipo_advisor.py` slots into Phase 3 (Deep Dive #3) and gets its real calibrator in Phase 4 (Deep Dive #4).

**The two load-bearing gates**, echoing the equity system's kill-gate:
- **Deep Dive #4 — the reliability gate.** No probability ships to a user until predicted-vs-actual tracks the diagonal and the look-ahead shuffle collapses skill to chance.
- **Deep Dive #5 — the GMP re-calibration gate.** GMP stays in the model only if it measurably improves calibration; otherwise it comes out.

*This suite is an engineering/research reference, not financial advice. The system is advisory only — it places no orders; the operator bids and sells by hand. A calibrated probability is an estimate, not an assurance.*
