# V3 PROGRESS LOG

*Maintained per `docs/v3/MASTER_BLUEPRINT_v3.md` Part VIII. One row per item as it moves.*

| Date | Item | Type | Outcome | Notes |
|---|---|---|---|---|
| 2026-07-14 | BUG 1 — stale verdicts under a fresh-looking timestamp | bug | fixed (branch `fix/bug1-freshness-truth`, pending review) | Diagnosis-first. Defect 2 (freshness truth): the chip was bound to react-query `dataUpdatedAt` (local API-answer time) while `refresh_from_nse` never surfaced failure — structurally unable to report staleness. Added `IngestStateStore` + `GET /status`; `last_success` advances only on a confirmed NSE pull, persisted, failures visible ("… · retrying"). Defect 1 (on-open refresh): nothing client-side could trigger a real pull (empirically confirmed — 29 `/board` reads → 0 NSE fetches; only the scheduler timer/boot pull). Shell-owned trigger over a parent-only stdin channel on window focus/restore + Refresh button; engine-side debounce (~15 s). Renderer stays read-only, API stays GET-only. Scoring path byte-identical: MAX \|Δprob\|=0.0 across 386 IPOs, git-proven (nothing under model/calibration/features/core, models/, config/). +12 tests; ruff/mypy/tsc green; verified live (green chip) + stdin-channel harness (debounce + real pull). |
