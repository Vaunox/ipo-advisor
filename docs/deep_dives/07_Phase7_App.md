# Phase 7 — The App (mini-blueprint)

### Building the IPO Advisor's front end: a Windows `.exe` that installs and behaves like genuine software (Discord/Steam class), with the UI designed iteratively in Figma.

*Phase 7 is the only phase where **taste** matters — the Phase 6 engine doesn't care what it looks like; the app does. So the UI is its own iterative mini-project with the operator in the loop. The model and service are finished and gated; this phase puts a body on the brain. Engineering/research reference — not financial advice.*

---

## The two loops (read first)

Phase 7 is **two sequential loops**, not one. Do not collapse them.

1. **DESIGN loop (Figma)** — iterate the *look* with operator feedback until approved. **No app code.** Cheap, fast to change. AI proposes, operator reacts, AI refines.
2. **BUILD loop (code)** — translate the *approved* design into the real front end, wrap it in a native desktop shell, package it as installable software. Refine the *running* app against the design.

Settle the look in Figma (where a change is seconds) **before** building (where a change is work). Iterating visuals directly in code is slower and is not the plan.

A Figma file is a **picture of the UI, not the running UI.** Approving the Figma does not mean the app is done — it means the build loop can begin against a locked design.

---

## What the app must show (FIXED content spec — design serves this)

This is the *content*; the design loop decides how to *present* it. It is not up for redesign — only its presentation is.

- **IPO list** — current/open and upcoming mainboard IPOs, each with a verdict badge.
- **Verdict** — `APPLY` / `MARGINAL` / `SKIP` / `INSUFFICIENT_SIGNAL`, clear and prominent.
- **Calibrated probability** — shown **only when the reliability gate passes**; otherwise show the **UNCALIBRATED** banner and **no number** (inherited Phase-6 rule).
- **Grounded reason** — the plain-language reason with the actual feature values (e.g. "QIB 38×, anchors 85%").
- **Watch items + kill-flags** — the secondary cautions and any hard overrides.
- **Cold-market caveat** — when `market_regime` is soft/cold, surface the flag's caveat ("cold market — probability less certain"). This is annotation, not a number change.
- **Net-of-cost listing-gain estimate** — gross and net (after STT/DP/exchange/GST).
- **Per-IPO detail** — subscription figures (QIB/NII/retail), issue structure, the verdict's full reasoning.

**Explicitly NOT shown:** **GMP.** GMP failed its gate and is out of the shipped model. The UI must not present GMP as a scoring input or imply it drives the verdict. (If ever surfaced later, only as clearly-labeled non-scoring context — not in v1.)

**Explicitly NOT present:** any **order / buy / apply-for-me / action** control. The app is advisory; it displays verdicts, it never transacts. No "Buy" button, ever.

---

## DESIGN loop — AI proposes first

The operator does **not** state a vibe up front. Reacting to something concrete is far easier than describing taste from a blank page. So:

### Round 1 — AI proposes a complete first direction (no interrogation first)
- AI designs a **real, concrete dashboard in Figma** — IPO list + a verdict-detail view — choosing a defensible starting point itself (clean, verdict-forward; light or dark is the AI's call). It anchors the proposal to the *content* (a fast decision tool: a clear verdict, a probability, a reason), not to a random aesthetic.
- AI presents it with a **one-line rationale** ("verdict-forward and minimal because this is a fast decision tool") so the operator knows what choice to accept or reject.

### Rounds 2+ — refine on feedback
- **Operator reacts in plain language** — "too cluttered," "make the verdict bigger," "wrong colors," "I like this."
- **AI refines, and asks targeted questions ONLY where the feedback is genuinely ambiguous** — one or two at a time, never a survey, and never asking what it can decide itself.
- **AI proposes, operator disposes** — AI commits to choices and defends them briefly; it does **not** dump ten options each round for the operator to sort (that pushes the work back onto the operator and defeats the point).
- **One area changed per round where possible**, so the operator sees the effect of their feedback rather than everything shifting at once.
- AI shows the **actual Figma each round**, not descriptions.

### Done = operator approves
The design loop ends only when the operator says "this is it." That approved Figma is the locked spec the build loop targets. No build work starts before approval.

**Convergence guardrails** (so the loop doesn't drag): the AI starts concrete (round 1 is a full design, not questions), changes one area at a time, and decides defensible details itself rather than asking. Aim to converge in a handful of rounds.

---

## BUILD loop — translate approved design → genuine software

Only after the design is approved.

1. **Front end** — build the approved design as the **PWA / React dashboard** (`apps/pwa/`). Use Figma's handoff (specs/tokens/component extraction) to match the design faithfully. Refine the *running* UI against the Figma until it matches and feels right.
2. **Native desktop shell — Electron (the decision, not Tauri).** Wrap the front end in **Electron**. The **Python FastAPI engine** runs as a bundled **sidecar process** the shell launches, health-checks (`/health`), and shuts down on quit. Electron is chosen for **build-path certainty over footprint**: no new language toolchain (vs Tauri's Rust chain compounding the novel sidecar wiring), the deepest Python-sidecar prior art (`child_process` + `electron-builder`/`electron-updater`), and the most-proven path (VS Code/Slack/Discord). Accepted tradeoff: the ~150 MB Chromium bundle — a non-issue for a single-operator app installed once. (Full rationale: Deep Dive #6, Module D.)

   **Sidecar lifecycle (build-critical).** The Python FastAPI engine runs as a PyInstaller'd binary that the Electron shell spawns and manages. This is where the Electron-plus-Python integration usually gets fiddly, so handle it explicitly in the **first** build, not patched later. Get all four right:
   - **Free-port selection** — do not hardcode the engine's port; a fixed port collides with whatever else the user is running. Pick a free port at launch (or let the OS assign one) and pass it to both the spawned engine and the UI.
   - **Readiness gate before the UI calls the engine** — the UI must not issue requests until the engine is actually up. Spawn the engine, then poll `/health` until it returns OK (with a timeout), and only then load/enable the UI. Loading the UI first is a race condition that shows errors on a cold start.
   - **Clean teardown on quit** — kill the Python process when the app exits, on **every** exit path (window close, quit, crash, OS shutdown). Orphaned backend processes left running after the app closes are the classic Electron+sidecar bug — guard against it explicitly (track the child PID; kill on `before-quit`/`will-quit` and on unexpected shell exit).
   - **Surface engine-down state** — if the engine fails to start or dies mid-session, the UI shows a clear "engine unavailable" state, not a frozen or silently-broken screen.

   *Phase-7 gate check:* launch/quit the app repeatedly and confirm **no orphaned Python processes** remain, and that a cold start **never shows the UI before `/health` is green**.
3. **"Genuine software" packaging** — the deliverable installs and behaves like Excel/Steam/Discord:
   - A proper **installer** (Program Files, Start Menu + desktop shortcuts, registered **uninstaller** in Add/Remove Programs).
   - **App icon** + proper window identity (title, taskbar).
   - **Clean native window** — no browser chrome, no address bar.
   - **System-tray presence** + **native OS notifications** (the Phase-6 notifier surfaces as real Windows notifications on an APPLY crossing).
   - Remembered window size/position; optional launch-on-startup; note the **auto-update** path even if deferred.
4. **Android — out of scope (removed, not deferred).** Not part of v1. The same read-only API could later back a thin Android client, but it is not built here.

---

## Invariants the UI MUST NOT break (inherited from Phase 6)

The app is a **face on the gated engine** — it displays what the engine produces and must not become a back door around any guarantee:

1. **No recomputation.** The UI shows the engine's verdict/probability verbatim (read through the existing GET-only API). It never re-derives a verdict or a number, and there is no second scoring path in the front end.
2. **The reliability gate holds in the UI.** When the calibrator hasn't passed the gate, the app shows the **UNCALIBRATED banner and no probability** — never a number the gate didn't bless.
3. **Calibration stays sacred.** The cold-market caveat is **annotation only** — it never changes the displayed probability. (Same principle as the engine: a flag informs, it doesn't move the number.)
4. **Advisory-only, structurally.** No order/action/buy control anywhere in the UI. The app cannot transact because nothing in it can.
5. **GMP is not a scoring input in the UI.** Out of the model, out of the verdict presentation.

A Phase-7 gate pass requires the running app to honor all five — the UI is allowed to make the engine's output *beautiful*, never *different*.

---

## Sequence summary

1. **Design loop (Figma):** AI proposes a full first design → operator reacts → AI refines + asks only where ambiguous → repeat → **operator approves.**
2. **Build loop:** approved design → PWA/React front end → **Electron** native shell (engine as a bundled sidecar) → installer/icon/tray/notifications → installable genuine-software `.exe`.
3. **Phase-7 gate:** the `.exe` installs like real software, launches the bundled Phase-6 engine, shows live verdicts, fires native notifications on APPLY crossings — and honors all five inherited invariants. Tag `gate-7-app`.

*Engineering/research reference, not financial advice. A calibrated probability is an estimate, not an assurance; the app is advisory only and places no orders.*
