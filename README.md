# IPO Listing-Gains Advisor — Build Handoff

This folder is a **build handoff** for a coding agent (e.g. Claude Code). No source code is included yet — the agent builds it from these specs, phase by phase.

## Contents
- `MASTER_BLUEPRINT_IPO_Listing_Advisor_Handoff.md` — the spec to build from, top to bottom. Engineering ground rules, locked decisions, the seven-layer architecture, and a phase-gated build program (Phase 0 → the Windows `.exe` + Android APK).
- `docs/deep_dives/` — full rationale per layer. Open the matching deep-dive at the start of each phase. Start with `00_DeepDives_Index.md`.

## How to start the build
Open this folder in Claude Code and say:

> "Read `MASTER_BLUEPRINT_IPO_Listing_Advisor_Handoff.md` and `docs/deep_dives/00_DeepDives_Index.md`. Follow the Engineering Ground Rules (Part I). We're building **Phase 0**. Read its reference and Deep Dive #1, build every deliverable to the GATE criteria, write the tests, update the Progress Log, then make one commit `feat(p0): …` and tag the gate."

Then proceed one phase at a time, not advancing until each GATE passes.

## The two hard checkpoints (do not skip)
- **Phase 4 — the reliability gate** (Deep Dive #4): no probability is shown to a user until the calibrator tracks predicted-vs-actual and the look-ahead shuffle collapses skill to chance.
- **Phase 5 — the GMP re-calibration gate** (Deep Dive #5): GMP stays in the model only if it measurably improves calibration; otherwise it is removed.

## Before Phase 4
The calibration gate needs **≥100 past mainboard IPOs with clean listing-day labels**. Confirm that sample can be assembled (Phase 1) before relying on the calibrated probabilities.

---

*Engineering/research reference, not financial advice. The system is advisory only — it places no orders; the operator bids and sells by hand. A calibrated probability is an estimate, not an assurance.*
