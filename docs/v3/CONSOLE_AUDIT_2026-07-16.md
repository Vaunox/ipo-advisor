# CONSOLE AUDIT — silent-outcome pass (V3-16 Stage 1)

*Re-run + extension of the console audit, verified against `main` at `ad1f478` (2026-07-16). This is the
**audit + honest-logging pass** that must precede V3-16 (the read-only debug console). It is **report-only** —
no logging is applied and the console is **not** built or designed here. Nothing below is merged until the
operator approves it.*

> **Note on the prior audit.** The task referenced a parked audit at `docs/v3/CONSOLE_AUDIT_…md`. That file
> does **not** exist anywhere reachable — not on `main`, not in any branch, stash, or git history (checked
> `git log --all --diff-filter=A`), not on disk. The only surviving trace of prior audit work is **finding-④**
> (the listing-strand detector, merged `9f680fd`) recorded in `V3_PROGRESS.md`. This audit was therefore
> **re-derived from scratch** against current `main`, and extended to all the code that has landed since
> (VM data plane, VM↔local fallback, the overdue-listing detector, the new-IPO onset trigger, the archive
> snapshot job, and the just-merged `live.py` subscription-fetch fix). Persisting *this* audit as a tracked
> doc is deliberate — so it is not lost the way its predecessor was.

---

## The bar this audit enforces

A developer reading the log should be able to understand the full working of the app and diagnose any issue
**without reading the source**. The log is a **heartbeat, not an alarm**: every meaningful operation announces
itself on **both** outcomes — success (INFO) *and* failure/degrade (WARN/ERROR) — and every branch is named
(`served_from_vm` ≠ `served_from_local_fallback`; "abstained because the fetch failed" ≠ "abstained because
there is genuinely no data"). A silent success is nearly as bad as a silent failure: it leaves a hole in the
narrative where you cannot tell "this step ran fine" from "this step never ran."

**Counterweight (equally important): do NOT over-log.** Log at the level of *meaningful operations* — a fetch
resolved, a cycle began/ended, a data path chosen, a verdict changed, an error occurred. Not every function
call, loop iteration, or trivial helper. A section at the end lists what was **deliberately not flagged** and why.

## The event shape to match

The engine already emits structured JSON via `ipo.core.logging` (`get_logger` → `JsonFormatter`). Every line is
`{ts, level, logger, message, …extra}` where **`message` is the named, greppable event slug** and structured
fields ride in `extra={…}`. Secrets are redacted **structurally at the sink** (token/PAN/Bearer/JWT), so no new
log call can leak one. The gold-standard example already in the tree:

```python
_log.warning("live_subscription_fetch_failed",
             extra={"symbol": issue.symbol, "error": str(exc),
                    "preserved": preserved, "outcome": outcome})
```

All proposed events below follow this exact convention (slug in `message`, fields in `extra`, reuse `_log`).

---

## Summary of findings

| # | Where | Shape | Group |
|---|---|---|---|
| A1 | `service/scheduler.py` `run_cycle` | Silent success — the core cadence loop emits **nothing** | Logging gap |
| A2 | `service/scheduler.py` / `transitions.py` | Silent success — **verdict changes are never logged** (only written to JSON) | Logging gap |
| A3 | `service/runner.py` `main` | Silent success — no startup line (config facts: live_ingest, vm, data_dir) | Logging gap |
| A4 | `service/runner.py` `_provision_data_dir` | Silent substitution — store + transition log **deleted** on seed-version bump, unlogged | Logging gap |
| A5 | `data/ingest/live.py:104` `build_live_records` | Silent degradation — forthcoming feed fails → `[]`, current-only, no line | Logging gap |
| A6 | `data/ingest/live.py:214` `resolve_listings` | Silent substitution — bhavcopy price fetch fails → `None`, no line | Logging gap |
| A7 | `scripts/refresh_context.py:139,143` `_context` | Silent substitution — per-IPO detail fetch fails → `{}`, indistinguishable from "no data" | Logging gap (VM plane) |
| A8 | `scripts/run_live_ingest.py:121` new-IPO onset | Branch not distinguished — `_pull_empty` conflates not-listed / no-fields / fetch-failed | Logging gap (VM plane) |
| A9 | `src/ipo/vm/server.py:75` `/context` | Silent substitution — corrupt cache → empty `{}` served, no line | Logging gap (VM plane) |
| A10 | `scripts/vm_archive_snapshot.py:31` `sync_snapshot` | Silent degradation — missing source file → `copied=[]` looks like a healthy sync | Logging gap (VM plane) |
| A11 | `data/sources/base.py:217` `fetch_bytes` | Silent retries — unlike `fetch`, bhavcopy retries emit no `fetch_retry` | Logging gap (minor) |
| A12 | `data/hygiene/clean.py:100` `merge_partials` | Silent-ish — cross-source conflicts counted but not individually logged | Logging gap (minor, batch) |
| A13 | `scripts/refresh_context.py:198` `merge_context` | Silent substitution — corrupt cache read → reset to a **single** entry (data loss) | Logging gap (minor) |
| **B1** | **`service/runner.py:338` `loop()`** | **Resilience — an unhandled cycle exception silently kills the scheduler thread; the engine freezes while looking alive** | **Correctness / needs a real fix** |
| B2 | `service/runner.py:346` `stdin_refresh_loop()` | Resilience — same class; a raised cycle silently ends on-open refresh | Correctness (minor) |

**Verdict-changing (value-flip) paths:** exactly **one** existed — the `live.py` subscription-fetch bug — and it
is **already fixed** (the worked example). This audit found **no other silent path that changes a verdict's
value.** B1 is a resilience defect (it *freezes* verdicts, it does not compute a wrong one) — see its section for
the precise characterization and why it still deserves a real fix, not just a log line.

---

## GROUP A — ordinary logging gaps (add a line; no behavior change)

*Every A-item is a pure logging addition: the code path is unchanged, so `MAX|Δprob|=0.0` holds trivially (no
files under `model/ | calibration/ | features/ | core/config.py`). Each proposes the **success (INFO)** and
**failure/degrade (WARN/ERROR)** forms with the branch named.*

### A1 — the scheduler cycle is completely silent  ★ highest-value gap

**Where:** [`service/scheduler.py:79`](../../src/ipo/service/scheduler.py) `ScoringScheduler.run_cycle` — and the driving `loop()` in [`service/runner.py:338`](../../src/ipo/service/runner.py).

**Swallowed outcome:** `run_cycle()` is the heartbeat of the whole app — refresh → score → diff → emit. It emits
**zero** log lines. During a normal cycle you should see a bracketed sequence; today the file is silent between
whatever the refresh path happens to log. There is no way to see "a cycle ran and scored N IPOs," no cadence
signal, and — most damaging — if cycles **stop**, the log simply goes quiet with nothing that said what a
healthy cycle even looked like. This is the exact "a six-line cycle emits four and stops" scenario, except it
emits nothing.

**Proposed events (bracket the cycle):**
- Success start: `scheduler_cycle_start` (INFO) `extra={cadence_minutes, open_books, asof}`
- Success end: `scheduler_cycle_done` (INFO) `extra={scored, transitions, became_apply}`
- The failure form is **B1** (`scheduler_cycle_failed`, ERROR) — because catching it is also the resilience fix.

Also worth a low-volume line when the cadence **changes** band (the "data path chosen" signal):
`scheduler_cadence` (INFO) `extra={minutes, reason: "book_open" | "default"}` — emitted only on a change, not every cycle.

### A2 — verdict changes are recorded but never narrated  ★ this is "verdict emission"

**Where:** the transition is built in [`service/scheduler.py:101`](../../src/ipo/service/scheduler.py) and persisted in [`service/transitions.py:57`](../../src/ipo/service/transitions.py) `TransitionStore.record` — **neither logs.**

**Swallowed outcome:** a verdict *changing* (e.g. `INSUFFICIENT_SIGNAL → APPLY` at close, or a crossing INTO
APPLY) is the single most meaningful thing the engine produces. Today it is written only to
`verdict_transitions.json`; the **log** — what the debug console will show — never mentions it. A developer
watching the console during a live close-day window would see no sign that the app just flipped an IPO to APPLY.
The user-facing alert path (`LogNotifier`→`ipo_alert`, or the runner's `push_transport`→`notify_crossing`) fires
**only** when `notify.enabled` and the channel isn't `none` — so with notifications off, the crossing is
invisible everywhere. The narrative must not depend on the notify channel.

**Proposed event (the success line for "a verdict changed"):**
- `verdict_transition` (INFO) `extra={ipo_id, from_verdict, to_verdict, probability, crossed_into_apply}` — emitted at the scheduler's `on_transition` point (richest context; fires once per genuine change, never the steady state, so no per-cycle spam).

No separate failure form — it is an observation. (Recommend logging in the scheduler rather than `TransitionStore.record`, keeping the store a pure persistence layer; operator's call.)

### A3 — no startup banner

**Where:** [`service/runner.py:247`](../../src/ipo/service/runner.py) `main`, right after `configure_logging`.

**Swallowed outcome:** when the engine boots, the first thing a diagnostician wants is *what mode am I in?* —
is live ingest on, is a VM configured, which data dir, what log level, frozen build or dev. Today the first log
line is whatever the first cycle emits; the boot conditions are invisible. If `live_ingest=false` (frozen data)
or `VM_BASE_URL` is unset, "why isn't it refreshing?" has no answer in the log.

**Proposed event:**
- `engine_starting` (INFO) `extra={data_dir, live_ingest, vm_configured, log_level, frozen}` — one line at boot.

### A4 — the data store is silently wiped on a seed-version bump

**Where:** [`service/runner.py:94`](../../src/ipo/service/runner.py) `_provision_data_dir` — `unlink(missing_ok=True)` on `ipo_records.parquet` and `verdict_transitions.json`.

**Swallowed outcome:** on a version mismatch (fresh install or an update that bumped `_SEED_VERSION`), the record
store **and** the verdict-transition history are **deleted**. A developer seeing an empty board / lost history
after an update has nothing in the log explaining it. This is a silent, destructive substitution.

**Proposed events (branch-distinguished):**
- Cleared: `data_store_cleared_on_version_change` (WARN) `extra={old_version, new_version, cleared}`
- Seeded: `data_store_seeded` (INFO) `extra={copied}` (when a bundled `_seed/` is copied in)
- No-op: nothing (unchanged version — not an event).

*Implementation note:* `_provision_data_dir` runs **before** `configure_logging` (runner.py:277 vs :282). The fix
must either move provisioning after logging is configured, or emit these lines after the fact — otherwise they hit
the uninitialised root logger.

### A5 — the forthcoming (upcoming) feed fails silently

**Where:** [`data/ingest/live.py:102-105`](../../src/ipo/data/ingest/live.py) `build_live_records`.

```python
try:
    upcoming = client.upcoming_issues()
except SourceError:
    upcoming = []   # ← silent: current issues still ingest, but forthcoming IPOs vanish this cycle
```

**Swallowed outcome:** the docstring says "a forthcoming-feed failure degrades to current-only," but nothing is
logged. New IPOs that NSE has published with a price band but that haven't opened silently disappear from the
Upcoming calendar until the current-issue feed later picks them up. Not verdict-changing (pre-open IPOs abstain),
but a real "why is Upcoming empty?" mystery. Success is already covered by the cycle line (`live_refresh_done`);
only the degrade branch is silent.

**Proposed event:**
- Degrade: `live_upcoming_feed_degraded` (WARN) `extra={error}` — "forthcoming feed failed; ingesting current-issues only."

### A6 — the listing-day price backfill fails silently

**Where:** [`data/ingest/live.py:211-215`](../../src/ipo/data/ingest/live.py) `resolve_listings`.

```python
try:
    prices = client.listing_prices(issue.symbol, issue.listing_date)
except SourceError:
    prices = None   # ← silent: listing_date is stamped but open/close never recorded this cycle
```

**Swallowed outcome:** the bhavcopy fetch for a just-listed IPO fails and the price is silently left `None`. It is
retried within `PRICE_BACKFILL_DAYS`, and a *persistent* failure is eventually caught by the overdue detector
(finding-④, `OVERDUE_UNPRICED`) — so this is not catastrophic — but each individual failure is invisible, so a
flaky archive host looks identical to "not listed yet." Success is covered by the aggregate `listings_resolved`
count; the per-symbol failure is the gap.

**Proposed event:**
- Degrade: `listing_price_backfill_failed` (WARN) `extra={symbol, listing_date, error}` — "price fetch failed; will retry within the backfill window."

### A7 — the per-IPO Upstox context fetch fails silently  (VM plane)

**Where:** [`scripts/refresh_context.py:136-144`](../../scripts/refresh_context.py) `_context`.

```python
resp = _get(f"/v2/ipos/{ipo_id}", token)
if resp.status_code != 200:
    return {}          # ← silent: a 500/429 becomes indistinguishable from "IPO has no registrar/RHP"
...
if not isinstance(obj, dict):
    return {}          # ← silent: malformed body, same
```

**Swallowed outcome:** in the full-universe refresh (`main`), a per-IPO detail fetch that 500s or 429s silently
yields `{}` → the IPO is simply omitted from the cache (`if entry: ipos[sym] = entry`). A run where half the
detail calls failed looks the same as a healthy run with fewer fields — a failure disguised as genuine absence,
the exact shape this audit targets. (This script is **deliberately package-free** — no `ipo` import, so it can
run anywhere — so it cannot use the structured logger; the honest fix is a `stderr` line matching the existing
`_list_ids` style **plus** an aggregate.)

**Proposed (print-based, to match the script's existing style):**
- Per-failure: `print("[context {ipo_id}] HTTP {code}" | "malformed body", file=sys.stderr)` (mirrors `_list_ids`).
- Aggregate in `main`: `print(f"detail fetches: {n_ok} ok, {n_failed} failed")` — so a half-failed run is visibly different from a healthy one.

### A8 — the new-IPO onset pull collapses three outcomes into one  (VM plane)

**Where:** [`scripts/run_live_ingest.py:117-124`](../../scripts/run_live_ingest.py) `fire_new_ipo_context_pulls`.

**Swallowed outcome:** the honest branches here are good (`new_ipo_context_pulled` / `_pull_empty` /
`_pull_failed` / `_darkship`) — but `new_ipo_context_pull_empty` (returned `False` from `merge_context`) conflates
**three** distinct causes: the symbol was **not found** in the Upstox listing, it was found but had **no context
fields yet**, or (via A7) the detail fetch **failed**. The task's rule — "abstained isn't enough, say *why*" —
applies.

**Proposed:** thread a small status back from `refresh_and_merge_one` and split the slug:
- `new_ipo_context_pull_symbol_not_listed` (INFO) — resolved no id in the Upstox listing.
- `new_ipo_context_pull_no_fields` (INFO) — found, but the entry was empty.
- (fetch failure already surfaces via A7's stderr + the existing `_pull_failed` on exceptions.)

### A9 — the VM read-API serves empty context on corruption, silently  (VM plane)

**Where:** [`src/ipo/vm/server.py:70-77`](../../src/ipo/vm/server.py) `/context`.

```python
if not path.is_file():
    return {"refreshed_at": None, "ipos": {}}      # normal (dark-ship) — no log needed
try:
    payload = json.loads(path.read_text(...))
except (ValueError, OSError):
    return {"refreshed_at": None, "ipos": {}}      # ← silent: corrupt cache served as "empty"
```

**Swallowed outcome:** a corrupt context file on the VM is served to the app as *empty context* with no signal.
The app then shows "no registrar/RHP" for every IPO, indistinguishable from a genuinely empty cache. (The VM
configures structured logging via `run_vm_server.py` → `vm.log`, so this is actionable.) The missing-file branch
is a normal dark-ship state and needs no line.

**Proposed event:**
- Degrade: `vm_context_read_failed` (WARN) `extra={error}` — on the corrupt/unreadable branch only.

### A10 — the archive snapshot reports an empty push as success  (VM plane)

**Where:** [`scripts/vm_archive_snapshot.py:29-48`](../../scripts/vm_archive_snapshot.py) `_copy_if_present` / `sync_snapshot`.

**Swallowed outcome:** a missing source file returns `False` and is dropped from `copied` by omission. If
`ipo_records.parquet` is missing (the VM ingest never ran, or a wrong path) the job logs
`archive_snapshot_synced copied=[]` — a **bland success** that looks the same as a healthy sync with an empty
list. The records file being absent is a real problem; it should not hide inside an empty array.

**Proposed events (distinguish present vs expected-but-missing):**
- Missing: `archive_snapshot_source_missing` (WARN) `extra={file}` — per expected-but-absent file.
- Keep `archive_snapshot_synced` (INFO) but add `extra={copied, missing}` so `copied=[] missing=[records, context]` is loud.

### A11 — `fetch_bytes` retries are invisible (asymmetry)  (minor)

**Where:** [`data/sources/base.py:210-222`](../../src/ipo/data/sources/base.py) `fetch_bytes` vs `fetch:167-190`.

**Swallowed outcome:** `fetch` logs `fetch_retry` on every retry; `fetch_bytes` (used for the bhavcopy zip) retries
**silently**. A struggling archive host shows retries for JSON endpoints but nothing for the bhavcopy — an
inconsistency in the narrative.

**Proposed event:** mirror `fetch` — `fetch_retry` (WARN) `extra={url, attempt, delay}` in `fetch_bytes`.

### A12 — cross-source conflicts are counted, not named  (minor, batch path)

**Where:** [`data/hygiene/clean.py:100-104`](../../src/ipo/data/hygiene/clean.py) `merge_partials` (used by the batch `IngestPipeline`, not the live scheduler).

**Swallowed outcome:** a disagreement between an official source and an aggregator on a cross-checked field is
recorded into `MergeResult.conflicts` and only the **count** is logged (`ingest_complete`). The individual
conflict (e.g. "price: nse=500 vs aggregator=510") — a genuine data-quality event — never appears. Lower priority
because it is the operator-run backfill path and the report is returned, but it is a named-outcome gap.

**Proposed event:** `source_conflict` (WARN) `extra={field, sources}` per conflict, alongside the existing count.

### A13 — a corrupt context cache is silently reset to a single entry  (minor)

**Where:** [`scripts/refresh_context.py:197-205`](../../scripts/refresh_context.py) `merge_context` (the onset-trigger merge path).

**Swallowed outcome:** `merge_context` reads the existing cache; on a corrupt read it sets `existing = {}` and
then writes `{refreshed_at: None, ipos: {only-this-symbol}}` — **silently discarding every other IPO's context**.
Low probability (the full refresh writes the file), but a silent data-loss substitution. Adjacent robustness note:
`main` writes the cache with a plain `write_text` (non-atomic), while `merge_context` uses tmp+replace — a crash
mid-write in `main` is what could leave the corrupt file `merge_context` then wipes.

**Proposed:** on the corrupt-read branch, `print("[merge] existing cache unreadable — refusing to overwrite", file=sys.stderr)` and **skip the merge** (return `False`) rather than reset, so a bad read can never destroy good data.

---

## GROUP B — correctness / resilience (needs a real fix, not just a log line)

### B1 — an unhandled cycle exception silently kills the scheduler; the engine freezes while looking alive  ★

**Where:** [`service/runner.py:338-344`](../../src/ipo/service/runner.py).

```python
def loop() -> None:
    while True:
        with cycle_lock:
            service.run_cycle()          # ← no try/except
        cadence = service.scheduler.next_cadence_minutes()
        record_next_refresh(cadence)
        time.sleep(cadence * 60)
```

**Swallowed outcome:** `run_cycle()` is contracted to degrade rather than raise (`refresh_from_nse` never raises),
but that contract is not airtight — a parquet write hitting a full disk (`repository._flush_records`), an
`os.replace` failure in `IngestStateStore._flush`, a context `write_text` OSError, or any unforeseen exception in
scoring/notify will **propagate out of `run_cycle` → out of `loop()`**. Because `loop()` runs on a **daemon
thread with no supervisor**, the thread then **dies permanently and silently**. Uvicorn (the main thread) keeps
serving, so the app looks completely alive — `/health` is green, the UI renders — but **no cycle ever runs
again**: verdicts freeze at their last values forever, with **zero** signal in the log.

**Why this is more than a logging gap.** During a live close-day window this is the BUG-1 harm in a worse form —
the user can be shown a pre-surge verdict presented as current. It is **partially** mitigated: the BUG-1 freshness
discipline means `ingest_state.last_success` stops advancing, so the freshness chip eventually ages to
amber/stale — the user is not *fully* lied to. But the log itself gives no death rattle, and a diagnostician has
nothing to grep. Adding a log line alone does **not** fix it — you must also keep the loop alive. This is why it
is Group B.

**Characterization for the verdict-changing flag:** this **freezes** verdicts (serves the last-computed value); it
does not compute a *wrong* probability the way the `live.py` bug did. So it is a **resilience/correctness** defect,
not a value-flip. Called out separately per the task's instruction to distinguish these.

**Proposed fix (control-flow + logging):**
```python
def loop() -> None:
    log.info("scheduler_loop_started")
    while True:
        try:
            with cycle_lock:
                service.run_cycle()
            cadence = service.scheduler.next_cadence_minutes()
        except Exception as exc:                     # never let one bad cycle kill the loop
            log.error("scheduler_cycle_failed", exc_info=exc, extra={"error": str(exc)})
            cadence = _FAILSAFE_CADENCE_MIN           # bounded backoff, then try again
        record_next_refresh(cadence)
        time.sleep(cadence * 60)
```
`scheduler_cycle_failed` (ERROR) is also the **failure form of A1** (the cycle bracket).

**Proof obligation (earned, since this is not a pure logging add):** scoring path untouched — no files under
`model/ | calibration/ | features/ | core/config.py`, so `MAX|Δprob|=0.0` by construction (git-proven). But
because it changes control flow (it now catches what previously killed the thread), it needs a **behavioral test**:
inject a `run_cycle` that raises, assert (a) `scheduler_cycle_failed` is emitted and (b) the loop survives to run
the next cycle. That is the earned proof for this item — a resilience test, not a scoring test.

### B2 — the on-open (stdin) refresh dies the same way  (minor)

**Where:** [`service/runner.py:346-371`](../../src/ipo/service/runner.py) `stdin_refresh_loop`.

**Swallowed outcome:** `stdin_refresh_loop` also calls `service.run_cycle()` (line 366-367) with no `try/except`.
A raised cycle ends the stdin loop, so the window-focus / Refresh-button pull silently stops working (the
scheduler loop, if B1 is fixed, still runs — so lower impact). Same fix: wrap, log `stdin_refresh_failed` (ERROR),
continue reading stdin.

---

## Verdict-changing (value-flip) analysis — the critical flag

The task asks specifically for any silent path that **changes the verdict value** when it fails (the way the
`live.py` bug silently flipped verdicts to `INSUFFICIENT_SIGNAL`). Result of the sweep:

- **The `live.py` subscription-fetch bug was the one true value-flip — and it is already fixed** (see Confirmed).
- **No other value-flip remains.** The paths that *could* have been one were checked and are safe:
  - **VM records path** ([`data_plane.py:53`](../../src/ipo/data/ingest/data_plane.py)) — a failed/empty VM ingest cannot serve "fresh but empty." The VM's `/records` reports `refreshed_at = ingest_state.last_success`, which advances **only** on a genuine NSE pull (the BUG-1 discipline runs on the VM too, via `run_live_ingest.py`→`refresh_from_nse`). A stalled VM serves an **old** `refreshed_at` (chip ambers) over the **last-known** records, not an empty set. `upsert_many([])` is a no-op, so nothing clobbers.
  - **Context / registrar / RHP / lot / isin** — display-only, structurally walled off from the model (import-graph proven, `test_ipo_context.py`). A silent context failure (A7/A9) changes **display**, never a probability.
  - **`market_regime`** — flag-only, scorer weight 0; `None` on absence never moves a probability (out of scope anyway as model math).
  - **Notify channel off / `NullNotifier`** — suppresses the *user alert*, but the verdict is still computed and recorded; the crossing is a config choice, not a swallow (A2 makes it visible in the log regardless).
- **B1 is a verdict *freeze*, not a *flip*** — characterized above.

So there is **one** Group-B correctness item (B1, resilience) and **zero** remaining value-flips. B1 gets its own
earned resilience proof; every Group-A item is a pure logging add (`MAX|Δprob|=0.0` trivially).

---

## CONFIRMED ALREADY HONEST (the audit was thorough, not cherry-picked)

These paths already meet the bar — both outcomes, branch-distinguished — and are the templates the gaps should
match:

- **`live.py` subscription degrade** (the worked example) — `live_subscription_fetch_failed` with the four-way
  `outcome` (`scored_on_preserved` / `preserved_awaiting_close` / `abstained_stale_prior` / `abstained_no_prior_book`),
  plus `live_refresh_done` / `live_refresh_failed` / `live_record_skipped` / `listings_resolved` /
  `listing_resolve_past_failed`. ✔
- **`data_plane.py` VM↔local fallback** — both stores, both branches: `records_from_vm` ↔ `vm_records_fallback_local`,
  `context_from_vm` ↔ `vm_context_fallback_lastknown`. This is the model for "which path served." ✔
- **`run_live_ingest.py` new-IPO onset trigger** — `new_ipo_context_pulled` / `_pull_empty` / `_pull_failed` /
  `_darkship`, plus `run_live_ingest_done`. (A8 only refines `_pull_empty`'s branch split.) ✔
- **`ipo_context.py` ContextStore** — `ipo_context_cache_load_failed` on corrupt load, and the one `field_state`
  rule that distinguishes `present` / `not_loaded` / `stale` / `unpublished` — an absence never lies about *why*. ✔
- **`state.py` IngestState** (BUG-1 freshness truth) — `last_success` advances only on a confirmed pull;
  `ingest_state_load_failed` on corrupt state; every attempt recorded. ✔
- **`pipeline.py` IngestPipeline** — `source_degraded` per source failure, `bad_record` per unbuildable record,
  `ingest_complete` summary. ✔
- **`base.py` PoliteClient** — `fetch_retry` on retries, `robots_unreachable`, raises `SourceError` on exhaustion. ✔
- **`nse.py`** — parsers raise `SourceError` on shape drift (fail-loud by design; callers log). ✔
- **`telegram.py`** — `telegram_send_non200` / `telegram_send_error` on failed sends, with the 4×/day digest as a
  reconciling backstop. ✔
- **`vm_status.py` / `vm_health.py`** — pure honest read; a failed read-API probe or unreadable context becomes an
  explicit DEGRADED **row**, never a silent pass. ✔
- **`run_accuracy_monitor.py`** — surfaces `insufficient_sample` **distinctly** ("INCONCLUSIVE"), so "inconclusive"
  never reads as "healthy." ✔
- **`lifecycle.py` overdue detector** (finding-④) — pure predicate, surfaced **loudly** in two places (UI red badge
  + `run_heartbeat.py` `[OVERDUE]`, exit non-zero). One nuance below. ✔
- **`vm_heartbeat.py`** — writes the beat, logs `vm_heartbeat` with ingest/disk/ping outcome. ✔

*Nuance on finding-④:* the overdue strand is loud in the **operator ritual** and the **UI**, but an IPO *crossing
into* overdue during normal engine operation is not narrated in the **engine log** the console will show — it only
appears if/when the operator runs the heartbeat script. If the console should surface strands live, the scheduler
(A1) could emit an `overdue_listing_detected` (WARN) once per IPO on the crossing. Flagged as an **optional**
extension, not a gap (the strand is genuinely not silent today).

---

## Deliberately NOT flagged (the over-logging counterweight)

To keep the signal clean, these were considered and **left alone** — logging them would be noise:

- **Per-fetch success in `PoliteClient.fetch`** — every successful HTTP GET. The NSE client makes several per cycle
  (cookies, current, upcoming, per-symbol subscription, past, bhavcopy); logging each at INFO would drown the file.
  The cycle-level lines (`live_refresh_done`, `records_from_vm`) are the right granularity; failures already log.
- **Per-verdict scoring in `engine.py`** — `verdict_for` / `board` / `verdicts` re-score on **every** API read, and
  the UI polls `/board` + `/status` every ~5s. Logging per verdict = thousands of lines/hour. The meaningful event
  is the **change** (A2), not the recomputation. `engine.py` correctly stays silent.
- **Per-request handlers in `api.py`** — same reason; reads are not meaningful operations to narrate individually.
  (A global exception handler that logs API **500s** as structured events is a reasonable *future* nicety, but it is
  not a silent swallow — a 500 is visible to the UI — so it is out of scope here.)
- **`labels/builder.py:32` `label_skipped_no_listing`** — this **already** logs at INFO for every not-yet-listed
  record on every batch run. It is arguably a mild **over-log** (a not-yet-listed IPO having no label is normal, not
  an event). Batch-only and low-volume, so left as-is, but noted as the counterweight direction.
- **`get_updates` silent `[]`** ([`telegram.py:147`](../../src/ipo/service/telegram.py)) — the long-poll swallows
  transient errors to avoid spamming the poll loop; a truly dead poller is caught by the stale `bot.marker`. Correct
  as-is.
- **`repository.py`** — no logging, but it **raises** on corruption (loud), and its write failures are covered by B1.
  A low-level store should not narrate; its callers do.

---

## Scope audited

**In scope (traced end-to-end):** ingestion (`live.py`, `data_plane.py`, `pipeline.py`, `nse.py`, `base.py`,
`state.py`, `clean.py`, `labels/builder.py`, `repository.py`), listing resolution (`live.py::resolve_listings`,
`lifecycle.py`), context refresh (`refresh_context.py`, `ipo_context.py`, `run_live_ingest.py` new-IPO trigger),
scheduler cycles (`scheduler.py`, `runner.py` loop + stdin), API calls (`api.py`, `vm/server.py`, `vm/client.py`),
VM↔fallback selection (`data_plane.py`, `vm/client.py`), verdict emission (`engine.py`, `transitions.py`,
`notify/*`), archive (`vm_archive_snapshot.py`), monitoring/alerting (`monitoring.py`, `run_accuracy_monitor.py`,
`vm_status.py`, `vm_alert_check.py`, `telegram.py`, `vm_heartbeat.py`).

**Out of scope (per the task):** pure model math (`model/*`, `features/*`, `calibration/*`, `engine.py` scoring
internals), config/type parsing (`core/config.py`, `types.py`, `constants.py`, `secrets.py`), UI rendering
(React/Electron) — no UI path was found to silently swallow a *data* error (the one that mattered, the freshness
chip, was fixed by BUG-1). **Dead code (excluded):** `scripts/archive_pull.py` + `ipo.archive.pull` / `validate` /
`merge` are **retired** (operations/README.md:406,555 — "left in place, unused; nothing pulls into ipo-archive
anymore"); superseded by the snapshot job. Batch/offline operator rituals (`run_backfill`, `run_calibrate`,
`fetch_vix`, …) were not deep-audited beyond the shared `pipeline.py`.

---

## Proposed next steps — then PAUSE for review

1. **Operator reviews this audit** — confirm the groupings, the event names/branches, and especially the B1
   characterization + fix.
2. On approval, apply in a small number of reviewable commits on this branch (`audit/v3-16-console-honest-logging`):
   - **Group A** as pure logging additions (one proof: `MAX|Δprob|=0.0`, git-proven scoring path untouched).
   - **B1/B2** as a resilience fix with its **own earned proof** (the injected-exception-survives-the-loop test),
     plus the scoring-path-untouched proof.
3. Gate + pause before merge, per the v3 workflow (branch-first, gate-then-merge, main stays clean).
4. **Only then** does V3-16 (the read-only console screen) begin — a **separate** task. This audit does **not**
   build, design, or scaffold the screen.

**STOP.** Awaiting operator approval of the audit and the proposed logging changes before any are applied.
