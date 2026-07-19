# Operations Manual — how to keep the IPO Advisor running

*This is the **how** — the living procedures you actually run to operate and maintain the app when
you return to it occasionally. It is deliberately separate from [`docs/PROJECT_LOG.md`](../docs/PROJECT_LOG.md),
which is the **why** — the closed, archival evidence for how the model is shaped. When you come back
in six months to recalibrate or rebuild, read this file, not the codebase.*

**The scripts stay where they are** (`scripts/`) — they are wired and used. This folder documents
them; it does not relocate anything. Run everything **from the repo root** with the project venv:

```
# Windows (this machine)
.venv\Scripts\python.exe scripts\<name>.py [args]
# …or activate first:  .venv\Scripts\Activate.ps1   then:  python scripts\<name>.py
```

The golden rule that governs all of this: **a feature is never in the number until calibration earns
it, and the shipped calibrator never changes silently.** Recalibration produces a *candidate* you
review and promote by hand; nothing here auto-swaps the model users run.

**This repo is public.** Wherever this manual references the VM, `` `<VM_IP>` `` and `` `<vm-user>` ``
are placeholders — the real host and login live in a local/private operator note, not here. Substitute
them yourself when running any command below against the actual box.

---

## 1. Routine health checks — run periodically, read the result

None of these change the model. Run them after a batch of new listings, or on a calendar reminder.

| Check | Command | When | Reads OK as… | Concerning result |
|---|---|---|---|---|
| **Data-source heartbeat** | `python scripts/run_heartbeat.py --data-dir <app data dir>` | Monthly, and before any recalibration | `OK` (all fresh) or `WARN` (expected stale feeds — see §4) | **`ERROR — a required artifact is MISSING`** (exit 1): `models/calibrator.json` / `reliability.json` / a `data/backfill/*.csv` is gone. Restore it. · **`ATTENTION — N listing(s) OVERDUE`** (exit 1, v3 finding-④): a book-closed IPO the Live→History resolution never completed — the symbol never matched in NSE past-issues, or its listing price never backfilled — so it is silently stranded under an "awaiting listing" label. Inspect the named IPO(s); see §5. `--data-dir` defaults to `data_store` (dev) — point it at the installed app's per-user `engine-data` dir to audit the real store. |
| **Verdict-accuracy / drift monitor** | `python scripts/run_accuracy_monitor.py` | Quarterly, or after ~20+ new listings | `OK - no drift` | **`DRIFT ALERT`** (exit 1): recent-window APPLY-precision Wilson-CI sits **entirely below** the OOS baseline, or recent ECE exceeds tolerance. → investigate, then recalibrate (§2). `INCONCLUSIVE` = recent window below `--min-window`, not judged. |
| **T+3 settlement stability** | `python scripts/run_t3_stability.py` | Yearly, or after a settlement-rule change | `STABLE` (ECE shift ≤ 0.030, CIs overlap) | `DIFFERENCE` — but read the cause. Expected to read `DIFFERENCE` on the full 358 set purely from cold-era composition in the pre-cutover bucket (see [PROJECT_LOG §4.6](../docs/PROJECT_LOG.md#46-t3-stability)); a *settlement-driven* difference (matched composition) is the real signal → recalibrate on post-cutover data. **Regenerates `docs/T3_STABILITY.md`.** |
| **Recalibration-reproduces (dry run)** | `python scripts/run_recalibration_check.py` | Before trusting any re-fit; part of the recalibration ritual | **`REPRODUCES` (max delta 0.0)** — the fit is deterministic | **`MISMATCH`** (exit 1): the shipped calibrator is stale vs current data/code. → run the recalibration ritual (§2). **Writes nothing** — safe to run anytime. |

**Reading the monitor** (`run_accuracy_monitor.py`): it prints baseline vs recent APPLY precision (with
95% Wilson CI + `n_apply`), ECE, and base rate. A drift alert fires **only on a real departure** — the
recent CI must clear below baseline (not merely a lower point estimate), so ordinary small-sample noise
does not trip it. Tunable: `--window 60` (recent listings tested), `--ece-tolerance 0.03`,
`--min-window 20`.

---

## 2. The recalibration ritual — quarterly, and after a regime shift

**When:** every quarter (the heartbeat flags the calibrator `STALE` after 120 days), and whenever the
market regime shifts materially or the drift monitor alerts. Recalibration needs **new labelled
listings** in the backfill to be meaningful — refresh the data first.

**The discipline (do not shortcut this):**
1. A re-fit is only trustworthy if it is **deterministic** — a dry run must reproduce the current
   calibrator before you trust the pipeline.
2. `run_calibrate.py` sets the calibrator's gate flag to **`true` only if the reliability gate passes**.
   If the gate fails, the produced calibrator carries `passes_reliability_gate: false` and the app
   **withholds probabilities** (shows the verdict + UNCALIBRATED banner) — it does not ship a bad number.
3. The script **writes `models/calibrator.json`**, but that is a *working-tree candidate*, not a
   deployment. **You promote it explicitly** by reviewing the git diff and committing — and it only
   reaches users after a **rebuild + reinstall** (§3). Nothing auto-swaps the shipped model.

**Steps:**

```
# 0. Refresh inputs (only if you have new data to add)
python scripts/run_backfill.py          # re-pull / extend data/backfill/mainboard_ipos.csv (official NSE)
python scripts/fetch_vix.py             # refresh data/backfill/vix.csv (append-only)

# 1. Confirm the pipeline is deterministic BEFORE re-fitting (writes nothing)
python scripts/run_recalibration_check.py     # must print: REPRODUCES — max delta 0.0

# 2. Fit + gate the calibrator (writes models/calibrator.json + docs/CALIBRATION.md)
python scripts/run_calibrate.py
#    → read the printed gate table. PASSED = the candidate may ship. NOT PASSED = do not promote;
#      the app will withhold probabilities until a passing calibrator exists.

# 3. Refresh the held-out reliability report the UI serves (writes models/reliability.json)
python scripts/run_reliability_export.py

# 4. Review + promote by hand
git diff models/ docs/CALIBRATION.md          # inspect the parameter + metric changes
#    Sanity: sample_size grew as expected; gate PASSED; metrics within bounds (AUC≥0.55, ECE≤0.10).
git add models/ docs/CALIBRATION.md && git commit -m "recalibrate: <date>, N=<n>"

# 5. Ship it to your running app: rebuild + reinstall (§3).
```

If step 1 prints **MISMATCH** even before you add data, the shipped calibrator has drifted from the
current code/data — investigate that first (it usually means `models/calibrator.json` was hand-edited
or a feature-construction file changed without a recalibration).

---

## 3. Rebuild & repackage the app (also fixes a stale bundled calibrator)

The **source** always holds the current calibrator (`models/calibrator.json`), but a *previously built*
engine binary bundles whatever calibrator was current **when it was frozen**. After any recalibration —
or if you ever find the installed app running an old model — **rebuild from source**.

```
# One command (needs Node/npm + the venv Python on PATH; Windows Developer Mode ON — see the guide):
python packaging/build_app.py
```

This runs, in order: icon → **PyInstaller freeze of the engine** (bundles the current
`config` / `models` / `nifty` / `vix`) → PWA `npm run build` → desktop `npm run dist` (electron-builder
NSIS) → `src/ipo/apps/desktop/release/IPO-Advisor-Setup-<version>.exe`.

**Always verify the built engine carries the current calibrator** before reinstalling:

```
# Compare the bundled calibrator to the committed one — sample_size and hash must match.
.venv\Scripts\python.exe -c "import json; b=json.load(open('packaging/dist/ipo-engine/_internal/models/calibrator.json')); s=json.load(open('models/calibrator.json')); print('bundled', b['meta']['sample_size'], b['meta']['feature_code_hash']); print('source ', s['meta']['sample_size'], s['meta']['feature_code_hash']); print('MATCH' if b==s else 'STALE — rebuild')"
```

Expected today: **`sample_size 358`, hash `d01815d61aec4d33`, MATCH.** If it reads `STALE`, the build
picked up an old tree — re-run `build_app.py` from a clean source checkout. Then reinstall the produced
`.exe`.

**Full rebuild/repackage reference** (signing, the Microsoft Store MSIX target, and the Windows-11
`makeappx` workaround): [`docs/GATE7_PACKAGING.md`](../docs/GATE7_PACKAGING.md) — kept standalone as the
authoritative packaging guide.

---

## 4. Expected WARN states — not defects

The heartbeat (§1) will routinely print **`WARN`** for the feeds below. These are **deliberate
consequences of the deferred forward-recorder decision** (see [PROJECT_LOG §2](../docs/PROJECT_LOG.md#2-phase-history-p0p7)),
**not** problems to chase:

- **`[STALE] Nifty series (nifty.csv)`** — the Nifty regime series is not on a standing recorder; it
  only feeds the **weight-0 cold flag**, so staleness never moves a probability. Refresh it if/when you
  want the cold flag evaluated against current index history.
- **`[STALE] holiday calendar — covered only through <year>`** — the NSE holiday set is hand-maintained
  from the official circular (published each December). Add the next year's holidays to
  `src/ipo/core/constants.py` when convenient; until then the calendar simply flags that it needs the
  new year.

Only **`ERROR — a required artifact is MISSING`** (a missing calibrator / reliability report / backfill
CSV) is a genuine fault and exits non-zero.

---

## 5. Data freshness & manual refresh (v3 BUG 1)

The app now tells the honest truth about how current its data is, and lets you force a pull.

- **The "Updated …" timestamp = the last *successful* NSE pull**, not the last time the UI talked to
  the local engine. It advances **only** when a live NSE fetch actually lands — never on app open,
  render, or a local read. It is served by the engine's **`GET /status`** endpoint and persisted in
  the per-user data dir as **`ingest_state.json`** (`last_success` / `last_attempt` /
  `last_attempt_ok`). This file self-heals — if it's missing or corrupt the engine starts "blank"
  and the first successful pull repopulates it; it is safe to delete.
- **Amber "Updated … · retrying"** (header chip and Settings → Last refresh) means the store is still
  being served but the **most recent NSE pull failed** — the data is genuinely stale and the engine
  is retrying. This is the intended honest signal, not a crash. If it persists for hours, NSE is
  unreachable from this machine (check connectivity / whether NSE has started blocking the IP).
- **Opening or returning to the window triggers a real NSE pull.** The desktop shell asks the engine
  to fetch via a parent-only stdin channel (the renderer stays read-only and the HTTP API stays
  GET-only — no order/mutation path is introduced). The engine **debounces** (≈15 s), so a burst of
  focus events coalesces into one polite pull.
- **"Refresh now"** (Settings) and the **header Refresh** control do a **real** pull, not a re-read of
  the possibly-stale store. In a browser/dev context with no desktop shell, Refresh honestly falls
  back to re-reading the engine and says so (a live pull needs the packaged app).

None of this touches the model: `/status`, the freshness store, and the refresh trigger are all
outside the scoring path (verdicts/probabilities are byte-identical — proven per branch).

### Stranded listings — the overdue detector (v3 finding-④)

An IPO leaves Live and enters History once the engine stamps its `listing_date` (+ the listing-day
price) — `resolve_listings` does this by matching the closed issue against NSE's past-issues feed.
That match can **fail silently**: if NSE's symbol never matches the one we hold, the listing is never
stamped; if the bhavcopy price never backfills, the row is stamped but never priced. Either way the
IPO would otherwise sit forever under an "awaiting listing" label with nothing flagging it.

The app now **names the strand instead of hiding it.** Past the expected listing day + a
holiday-aware trading-day grace buffer, History's "Awaiting listing outcome" section shows the IPO as
**"listing overdue — resolution may have failed"** (or "…outcome overdue — price never recorded")
with an overdue count and a red badge, and the **heartbeat** (§1) prints an `[OVERDUE]` block and
exits non-zero — so a strand surfaces in the monthly ritual, not weeks later by noticing a badge.
**When it fires:** look the IPO up on NSE. If it *has* listed, the symbol we hold most likely differs
from NSE's past-issues symbol (fix the record / ingest mapping); if it genuinely hasn't listed yet,
the buffer clears it automatically once it does. The check is our-dates-only (no second data source),
so it stays truthful even when the Upstox context cache is stale or offline.

### The per-IPO Upstox context cache (v3 V3-5/V3-6+)

The **one** display-only Upstox cache feeds every per-IPO context field the app shows: the
Allotment tab's **registrar** (V3-6, deep-links to the registrar's own allotment-check site — the
app never handles a PAN), the detail page's **RHP link** (V3-5) and **bid lot** (V3-8, shown as an
*indicative* "≈ N shares · approx ₹…" — NSE provides lot_size on 0% of IPOs, so Upstox is the sole
source and it's never presented as an exact reported figure), the detail page's **ISIN + industry**
reference fields (V3-11, plain display metadata, no source named), and later the anchor list (V3-10).
One cache, one refresh, one staleness rule. It is **not** fetched by the app — it's an
occasional, token-free cache you refresh:

```
# needs your Upstox Analytics Token in the environment (or research/.env): UPSTOX_TOKEN=...
python scripts/refresh_context.py --data-dir <the app's data dir>
#   dev: --data-dir data_store   ·   installed app: the per-user engine-data dir the shell passes
```

- These fields are **fixed once filed and never change**, so this is occasional reference data —
  run it when new IPOs appear (like `run_backfill`), not on a cadence. It queries open+closed+listed
  (the RHP first appears at `open`).
- It writes `<data_dir>/context/ipo_context.json` (token-free, safe to share/commit/sync).
- **Degrades honestly:** a missing cache → the surface says "not loaded"; a per-IPO absence
  distinguishes "not yet published/filed" from **"cache is stale"** (the cache predates the IPO) —
  it never shows a stale value as current. Symbol-less (`'NONE'`) upcoming IPOs are excluded at
  ingest.
- **Severable & non-model:** the app only reads this cache; if Upstox is down you simply can't
  refresh — verdicts, probabilities, and live signals are entirely unaffected. Context data lives in
  a store separate from the model and can never become a scoring input (transitively import-graph
  proven: no `ipo.service.*` is reachable from the scoring path).
- **External links are host-allowlisted:** the app only opens pinned hosts — the eight registrar
  portals and the SEBI filing host (`sebi.gov.in`) for RHPs. An issuer-hosted RHP or any other URL
  renders as inert, copyable text, never a one-click open (a poisoned cache can't redirect the user
  to an attacker page).
- The script is **VM-runnable as-is** (pure Python + `requests`, no desktop assumptions): when the
  Part-II VM data layer lands it adopts this script unchanged as the VM-primary refresher, with
  local execution as the fallback — the same VM-primary/local-fallback discipline as every feed.

### The VM data plane (v3 V3-1) — VM-primary by default in the build, honest local fallback

The app reads its two data stores (the NSE record store and the Upstox context cache) from a **VM
read-API** — **VM-primary, with an honest local fallback**. As of the V3-1 flip (2026-07-16) the
**shipped `.exe` defaults to VM-primary**: the desktop build bakes the VM read-API base URL into the
binary, so a normal launch fetches from the VM first and only falls back to direct NSE scraping if the
VM is unreachable. The engine mechanism is unchanged and still **fails safe** — no URL configured, it
runs exactly as before the VM existed (pure local scrape).

- **How the URL is supplied (build-time, no IP in the public repo).** The runner reads `VM_BASE_URL`
  from its environment (`runner.py`, deliberately **not** an `IPO_*` key, so VM wiring can never leak
  into the model config). The desktop shell (`sidecar.ts` → `resolveVmBaseUrl`) sets it at engine
  spawn from, in priority order:
  1. a `VM_BASE_URL` already in the environment — runtime override / the **reversibility escape hatch**
     (set it empty to force local-only without a rebuild);
  2. **`src/ipo/apps/desktop/vm-config.json`** — GITIGNORED; holds the real URL (`http://<VM_IP>:8000`),
     and electron-builder bakes it into the `.exe` (it's on the `build.files` list). The VM IP was
     scrubbed from this public repo, so the real address lives **only** in this local file + the shipped
     binary; only **`vm-config.example.json`** is committed, showing the shape with a `<VM_IP>`
     placeholder. **To build a VM-primary `.exe`:** copy the example to `vm-config.json`, set the real
     URL, then `npm run dist`. Absent or still-placeholder value → the build ships **local-only**
     (fail-safe — never a silently-broken URL). GET-only base: `/health`, `/records`, `/context`.
- **Behavior:** each refresh pulls both stores from the VM; on any failure (unreachable, non-200,
  malformed/truncated envelope, timeout — 10s × 2 retries) that store falls back to local and the
  header sync chip says so honestly — **records** re-scrape fresh from NSE (still current), **context**
  keeps the last-known cache and ages (the Upstox token lives on the VM, so it can't self-refresh).
  Both stores from the VM → the chip stays quiet.
- **The VM side** is `scripts/run_vm_server.py --data-dir <vm-data> --host 0.0.0.0 --port <p>` —
  GET-only, serving whatever the VM's own fetch jobs (`run_live_ingest.py` for records + `refresh_context.py`
  for context, run **on** the VM) have written — **not** `run_ingest.py` (that is the seed/backfill
  pipeline; the VM needs the app's *live* NSE fetch, `run_live_ingest.py` → `refresh_from_nse`). It
  never runs the model, and the served data is public + token-free.
- **Read-only by construction:** the app can only READ from the VM — there is no mutation route in the
  read-API. The output half (app history → durable VM archive) is **V3-2**, and by design the **VM
  pulls** it (the app never pushes).

### The data VM's network state — firewall, rate limit, public IP (2026-07-18)

**Why this section exists:** these rules previously lived ONLY in the OCI console and in no repo
file, so their state was misread more than once — including a confident "any user anywhere can
reach the VM" that was exactly backwards (port 8000 was in fact pinned to one ISP block, so most
`.exe` users were silently falling back to local scraping). Nothing below is inferable from code;
if you change a rule in the console, change it here in the same sitting.

**Ingress rules** — *Default Security List for `vcn-20260704-1352`*, the only security list on the
VCN. The instance VNIC has **no Network Security Group** (`Network security groups: —`), so this
list is the *sole* cloud-side gate — there is nothing additive to look for elsewhere.

| Source | Proto | Port | Why |
|---|---|---|---|
| `0.0.0.0/0` | TCP | **8000** | The read-API. **Public on purpose** (opened 2026-07-18): every shipped `.exe` fetches from it, so any restriction silently degrades users to local scraping. Safe to expose — GET-only, no mutation route, no accounts/tokens, and the served data (NSE records + Upstox context) is public and token-free. |
| `<OPERATOR_ISP_CIDR>` | TCP | **22** | SSH, operator ISP block. |
| `0.0.0.0/0` | ICMP | 3, 4 | Path-MTU / unreachable signalling (Oracle default). |
| `10.0.0.0/16` | ICMP | 3 | Intra-VCN unreachable (Oracle default). |

**SSH is `/24`, NOT the `/32` that `operations/vm2/VM2_RUNBOOK.md` prescribes — a deliberate
deviation, not an oversight.** Key-only auth is confirmed on the box (`sshd -T` → `passwordauthentication
no`, `kbdinteractiveauthentication no`, `permitemptypasswords no`, `pubkeyauthentication yes`), so
brute-force is already ineffective and the marginal gain of `/32` over `/24` only binds against an
attacker who is *both* inside the operator's ISP block *and* holding the private key. Against that
thin gain, `/32` carries a real recurring cost: the ISP demonstrably reassigns the operator's address
**within** this block, so a single-IP rule would lock SSH out on every reshuffle. `/24` still refuses
~99.99% of the internet, survives the reshuffle, and leaves key-auth covering the remainder. If you
ever need to widen it in an emergency, the OCI console (Cloud Shell / serial console) is the way back
in — it does not depend on this rule.

**Both layers must agree.** Oracle's Ubuntu images ship their own `iptables` that drop most inbound
traffic, *independently* of the security list. On this box port 8000 is already accepted at the
instance level (`-A INPUT -p tcp -m tcp --dport 8000 -j ACCEPT`), so the console rule is sufficient
today — but if a port ever looks open in the console and still refuses connections, check `sudo
iptables -S INPUT` before anything else. That mismatch is the classic Oracle gotcha.

**Per-IP rate limit — 60 requests/minute, in the app itself.** Implemented in
[`src/ipo/vm/server.py`](../src/ipo/vm/server.py) (`_FixedWindowLimiter`), not in a proxy: there is no
nginx on this box, and uvicorn runs a **single worker**, so a process-local counter is coherent
without Redis. Deliberately **dependency-free** — `ipo.vm.server` is a PyInstaller *hidden import*, so
adding `slowapi` (or similar) would ship that library inside every desktop `.exe` for code the desktop
never executes. Over the limit → `429` + `Retry-After`; the limiter is registered *before* CORS so a
`429` still carries CORS headers instead of surfacing to a browser as an opaque cross-origin failure.
The dict of tracked IPs is capped (20k) and pruned, because an unbounded `{ip: state}` map is itself a
way to exhaust a 1 GB box. **The limit is sized for CGNAT, not for one user:** normal use is ~2 requests
per user per ~30-min ingest cycle, and Indian mobile carriers put many subscribers behind one public
IP, so that shared address must never trip it. Verified live: 60 pass, the 61st gets `429`, and a
20-user CGNAT cycle (40 requests) is untouched.

**The public IP `<VM_IP>` is EPHEMERAL, and cannot be converted.** Oracle is explicit: *"you
can't convert the ephemeral public IP to a reserved public IP with address 203.0.113.2."* The console
edit panel confirms it — the "Public IP type" radio offers only *No public IP* / *Ephemeral public IP*.
Taking a reserved IP therefore means **accepting a different address**, which would instantly break
every shipped `.exe` (the URL is baked in at build time). What that actually costs you:

- **Stop/start is SAFE** — *"When you stop an instance, its ephemeral public IPs remain assigned to
  the instance."* (An earlier note in this project claimed the opposite; it was wrong.)
- **Termination loses the address for good** — which is the real exposure here, since Always-Free
  reclamation *terminates* idle instances. That is precisely what the keepalive + the ≤30-day console
  login exist to prevent; treat both as load-bearing for IP stability, not just uptime.
- **The durable fix is a domain, not a reserved IP.** Point a hostname (e.g. `data.ipoadvisor.in`) at
  the VM and bake *that* into the `.exe`; then an address change is a DNS edit instead of a rebuild-
  and-redistribute. This also composes with the pending HTTP→HTTPS/TLS upgrade — do them together.

### The VM's Upstox context refresh — live (v3 V3-1) + token rotation

On the deployed VM (`<VM_IP>`), `refresh_context.py` runs **3×/day at 08:15 / 13:15 / 18:15 IST**
(`ipo-context.timer` → `ipo-context.service`, `Persistent=true` so a missed slot catches up on boot).
Each run writes `data/context/ipo_context.json`; `run_vm_server.py` serves it at `/context`. It is
cheap (~40s CPU, ~400 IPOs/run) — the fields are fixed once filed, so a few daytime passes are enough
to pick up newly-opened IPOs; this is the "occasional" cadence, not a live one.

- **Token:** `UPSTOX_TOKEN` in `/etc/ipo/context.env` (owner `root:root`, mode `600`), loaded into the
  service via `EnvironmentFile=` — systemd reads it as root and injects it into the `<vm-user>`-run
  process, so the secret file is never world-readable and never leaves the box (nor git; `/etc/ipo` is
  outside `/opt/ipo`). It is a **one-year read-only Analytics Token** (non-trading, no static-IP
  requirement, IPO-catalogue endpoints only) that **expires `01/07/2027`**.
- **Rotation (once a year, early July):** SSH to the VM, then:
  ```
  sudo nano /etc/ipo/context.env        # replace the UPSTOX_TOKEN=… line with the fresh token, save
  sudo systemctl start ipo-context.service   # immediate refresh, don't wait for the next slot
  ```
  **Set a calendar reminder for ~late June 2027** to mint and place the next token.
- **Degrades honestly:** if the token ever lapses, the refresh **fails loudly** (systemd logs a
  non-zero exit) and the context cache simply **ages** — records/NSE and every verdict are unaffected,
  nothing crashes. The surface shows context as stale rather than presenting a stale value as current.

### New-IPO onset context trigger (v3, display-only) — live

The 3×/day context baseline above can leave a genuinely new IPO's registrar/RHP/lot-size fields empty
for hours if it opens mid-interval (e.g. NSE lists it at 09:00, the next context batch isn't until
13:15). `run_live_ingest.py` (the 30-min records timer — unit `ipo-ingest.timer`/`ipo-ingest.service`,
reference copies in `operations/systemd/`) now closes that gap itself: after each
`refresh_from_nse` upsert, it diffs the post-upsert `ipo_id` set against a pre-upsert snapshot of the
same store — anything new fires **one** immediate single-symbol context pull via
`refresh_context.refresh_and_merge_one`, merged into the existing `ipo_context.json` (not a full
overwrite). The 3×/day baseline is unchanged; this only fills the onset gap for brand-new IPOs.

- **No separate "seen" set.** `ipo_records.parquet` (already the durable records store) IS the
  seen-state — "new" means "not in the store before this cycle's upsert." A VM restart never
  re-fires for an already-open IPO: the parquet file already has it, so nothing about it looks new to
  a freshly-started process.
- **Merge, not overwrite:** the single-symbol write only touches that one symbol's entry in
  `ipo_context.json` and deliberately leaves the top-level `refreshed_at` untouched (bumping it would
  falsely imply every OTHER cached IPO was just rechecked — see `merge_context`'s docstring in
  `refresh_context.py`). A field that IS found displays immediately regardless; an empty result just
  waits for the next real 3×/day batch to (correctly) label it, rather than mislabeling it early.
- **Dark-ships without `UPSTOX_TOKEN`** — same posture as the batch job. `run_live_ingest.py`'s own
  systemd unit therefore needs `EnvironmentFile=/etc/ipo/context.env` alongside
  `ipo-context.service`'s (same token, read by both units) for the trigger to actually fire on the
  box; without it, new IPOs simply wait for the next 3×/day slot as before (never an error).
  **Status: DONE.** Verified on the box 2026-07-19 — it is applied as the drop-in
  `ipo-ingest.service.d/environment.conf` (this line previously read as an outstanding step long
  after it had been carried out; reference copy now committed under `operations/systemd/`).
- **One symbol's failure never blocks another's**, and never affects the records ingest — the records
  write has already completed by the time context pulls fire.

### Updating VM code — the box is NOT a git repo (sync procedure + divergence risk)

`/opt/ipo` on the VM was set up by **direct file copy, not `git clone`** — there is no remote and no
`.git`, so **you cannot `git pull` to update it.** Code reaches the box only by `scp` of specific
source files, with three sharp edges:

- **Never `tar`/`scp` the whole `src/ipo` tree.** It carries the bundled electron `release/` / `build`
  / `node_modules` artifacts — ~**704 MB, ~14k files** (the ones mypy/ruff exclude); `tar src/ipo` will
  hang the ssh pipe. Copy **only the specific `.py` files** a change touches.
- **The box runs whatever was LAST scp'd, so desktop `main` and the box can silently diverge. A merge
  to `main` is NOT a deploy.** After merging you must scp the changed files (and restart the affected
  unit) for them to take effect; until then the box runs the old code.
- **Keep the sync file-list tied to the actual module set.** A newly-added telegram/vm module that is
  not on the list is silently absent on the box (its import fails only when its unit runs). Add new
  modules here and scp them.

**VM-relevant files (scp targets under `/opt/ipo/`):**

| Area | `scripts/` | `src/ipo/service/` |
|---|---|---|
| Records + read-API + context | `run_live_ingest.py`, `run_vm_server.py`, `refresh_context.py` | — |
| Durable archive (v3 V3-2 revised) | `vm_archive_snapshot.py` | — |
| Keepalive / heartbeat | `vm_keepalive.py`, `vm_heartbeat.py` | `vm_health.py`, `heartbeat.py` |
| Telegram (V3-3) | `vm_telegram_bot.py`, `vm_telegram_digest.py`, `vm_alert_check.py` | `telegram.py`, `telegram_format.py`, `telegram_alerts.py`, `telegram_commands.py`, `vm_status.py`, `oracle_login.py` |
| **Subscription series recorder (v3-DP DP-1)** | `run_live_ingest.py` (already listed above) | `vm_health.py`, `vm_status.py` (both already listed above) |

**DP-1 also adds a whole new package**, which the two-column table above cannot express — it is the
first VM feature to do so, and a package missing from the box fails only when the ingest unit next
runs. Copy the whole directory:

| Area | `src/ipo/` |
|---|---|
| Subscription series recorder (v3-DP DP-1) | `series/` (`__init__.py`, `models.py`, `store.py`, `state.py`, `recorder.py`) — plus the modified `data/ingest/live.py` and `data/sources/nse.py` |

The new-IPO onset trigger (below) touches no new file — it's entirely inside `run_live_ingest.py` +
`refresh_context.py`, both already itemized in the first row above. Nothing to add to this table for
it; **do** remember its systemd-unit change (`EnvironmentFile=` for the token) noted below.

The Telegram set includes the `/` command-menu code (`set_my_commands` in `telegram.py`, the
single-source `COMMANDS` in `telegram_commands.py`, the `setMyCommands` call in `vm_telegram_bot.py`).

**Procedure:** `scp <files> <vm-user>@<vm>:/opt/ipo/scripts/` (or `/opt/ipo/src/ipo/service/`), then
`sudo systemctl restart <affected-unit>`, then verify (e.g. the daemon re-registers its menu via
`getMyCommands`, a timer run posts to the group, or `journalctl -u <unit>`). The `.venv` editable
install picks up new `.py` files with no reinstall (no dependency changed). To sync several files
robustly on Windows, `tar` **only the named files** into a small archive and `scp` that (a streaming
`tar | ssh` pipe can hang in Git Bash).

### Durable archive (v3 V3-2, revised) — VM-write snapshot, live

**Decision (2026-07-15/16): the desktop drop is permanently dropped.** App-facing data (records +
final-close subscription + context) lives only as the parquet on the VM disk during normal operation;
a knowing tradeoff — if the VM is ever reclaimed, un-rescrapeable close-time values for already-closed
IPOs are lost forever for that stretch. What's preserved instead is a **durable, versioned, off-box
mirror**: the VM itself pushes a daily snapshot of `ipo_records.parquet` + `ipo_context.json` to
`ipo-archive`, so a reclaim loses at most since-the-last-snapshot data, not everything.

`ipo-archive` (`github.com/Vaunox/ipo-archive`) is now a **single-writer, append-only durable copy**,
not a two-source cross-check — the original "compromised VM can't corrupt the archive" guarantee (which
depended on the VM holding only a read-only key) is explicitly given up in exchange for the VM being
able to write. The replacement guarantee is **append-only at the repo level**:

- **Repo is deliberately public — do not "fix" this back to private.** GitHub branch protection/rulesets
  are Pro-only for private repos on this account; making the repo private again silently drops the
  append-only guarantee (force-push/deletion become re-allowed with no error, no warning — the API just
  quietly stops enforcing). Public was chosen knowingly: the data is KB-scale NSE subscription/context
  figures, this is a private downstream working copy with no attached app/site (unlike the desktop
  app's own privacy posture), and append-only durability was judged worth more than repo privacy here.
  If privacy is ever revisited, either accept losing append-only or pay for GitHub Pro first — never
  flip visibility without re-checking `branches/main/protection` survived the change.
- Only two files ever land in this repo — `ipo_records.parquet` and `ipo_context.json`, explicit
  filenames in `vm_archive_snapshot.py` (`RECORDS_FILENAME`/`CONTEXT_FILENAME`), never a glob or
  directory copy — so nothing else in the VM's data dir (logs, tokens, markers) can ever ride along
  even if that dir grows new files later.
- **Branch protection on `main`**: force-push disabled, deletion disabled (`allow_force_pushes: false`,
  `allow_deletions: false` — applied via Settings → Branches → rule on `main`, or
  `gh api -X PUT repos/Vaunox/ipo-archive/branches/main/protection -F required_status_checks=null -F enforce_admins=true -F required_pull_request_reviews=null -F restrictions=null -F allow_force_pushes=false -F allow_deletions=false`).
  A compromised VM can still **push new commits**, but can never rewrite or delete history.
- **VM deploy key is write-scoped**, generated **on the VM** (`ssh-keygen -t ed25519 -f
  /home/<vm-user>/.ssh/archive_write -N ""`), title `ipo-vm-archive-write`, registered with "Allow write
  access" checked. The prior read-only key (`ipo-vm-archive-readonly`) has been deleted from the repo's
  deploy keys — there is no reader role anymore.

**Mechanism — VM-side snapshot push, daily via systemd timer.** `scripts/vm_archive_snapshot.py` (pure
copy, git-free, unit-tested — [tests/unit/test_archive_snapshot.py](../tests/unit/test_archive_snapshot.py))
mirrors `<data_dir>/ipo_records.parquet` and `<data_dir>/context/ipo_context.json` into the
`/opt/ipo-archive` clone; the systemd unit's own shell step commits **only if something changed**
(`git diff --cached --quiet` guard — a no-op cycle produces zero commits) and pushes with the write key.
`/etc/systemd/system/ipo-archive-snapshot.service`:

```
[Service]
Type=oneshot
Environment="GIT_SSH_COMMAND=ssh -i /home/<vm-user>/.ssh/archive_write -o IdentitiesOnly=yes"
ExecStart=/opt/ipo/.venv/bin/python /opt/ipo/scripts/vm_archive_snapshot.py --data-dir /opt/ipo/data --archive-clone /opt/ipo-archive
ExecStart=/bin/bash -c 'cd /opt/ipo-archive && git add -A && { git diff --cached --quiet || git commit -q -m "snapshot $(date -u +%%Y-%%m-%%dT%%H:%%M:%%SZ)"; } && git push -q origin HEAD'
```

`/etc/systemd/system/ipo-archive-snapshot.timer` → `[Timer] OnCalendar=*-*-* 21:00:00 Asia/Kolkata` +
`Persistent=true`, `[Install] WantedBy=timers.target`; `systemctl enable --now
ipo-archive-snapshot.timer`. The repo's git identity is set locally (`git -C /opt/ipo-archive config
user.name/user.email`) matching the heartbeat repo's convention. **Live-verified 2026-07-15**: a manual
run pushed both files to `main` (commit `3c8801e`), and an immediate rerun with unchanged data produced
no new commit.

**Retired:** `ipo-archive-pull.service`/`.timer`, `scripts/archive_drop.ps1`, and the desktop "IPO
Archive Drop" scheduled task are all gone — there is nothing left to pull now that the desktop never
drops. `scripts/archive_pull.py` and its underlying `ipo.archive.pull`/`ipo.archive.validate` modules
are unused but left in place (dead, harmless, not wired to any unit) rather than deleted outright.

**Recovery** — to restore state on a fresh VM, `git clone` `ipo-archive` and copy `ipo_records.parquet`
/ `ipo_context.json` back into the data dir. This is now the *only* durable copy — there is no second,
independent backup of the drop as there was under the old two-writer design.

### VM monitoring, heartbeat & keepalive (v3 V3-3) — off by default; deploy runbook

Two independent mechanisms keep the VM data plane visible and alive; each ships dark and stands alone.

**Primary — heartbeat-staleness detector (always on, can't-itself-fail).** The VM writes a small
`heartbeat.json` (last beat, ingest freshness, free disk, keepalive marker) each cycle and pushes it
to a git **heartbeat channel**; your desktop `run_heartbeat --vm-heartbeat <clone>/heartbeat.json`
reads it and **names any failure honestly** (`VM heartbeat - last beat 1d ago — the VM's fetch cycle
may have stopped`, `VM ingest - NSE fetch failing …`, `VM disk - 4% free …`) and **exits non-zero**.
This needs *nothing alive on the VM* at check time and *no VM credentials on the desktop* — it's a
git-history read. It carries essentially every failure mode; with no `--vm-heartbeat` it's inert.

**Backup — one out-of-band liveness ping.** For the single time-sensitive, unrecoverable case (Oracle
reclaiming the instance), `vm_heartbeat.py` pings a free dead-man's-switch monitor (`HC_PING_URL`,
e.g. healthchecks.io) each cycle; the monitor emails you when pings **stop**. One liveness bit, not an
alerting stack. No `HC_PING_URL` → no ping (dark).

**Deploy (you provision):**

1. **Heartbeat repo (separate from the archive).** The VM *pushes* beats, so it needs a **write** key —
   which must never touch the durable archive (that key is read-only, above). So the heartbeat gets its
   **own throwaway repo** holding nothing precious: generate a second key **on the VM** (`ssh-keygen -t
   ed25519 -f /home/<vm-user>/.ssh/heartbeat_write -N ""`) and register its **public** half as a **write**
   deploy key on that repo alone — blast radius is liveness pings, nothing else. (This supersedes the
   earlier "a `heartbeat` branch of the archive repo, one key" note: a read-only archive key can't
   coexist with a shared heartbeat-write key.) Clone it on the VM; clone/reuse on the desktop.
2. **Dead-man's-switch** — create a check on healthchecks.io (or ntfy/Telegram), expected ~daily; put
   its ping URL in the VM env as `HC_PING_URL`.
3. **VM systemd — heartbeat** (`oneshot`, after each ingest / daily): `Environment=HC_PING_URL=…` and
   `Environment=GIT_SSH_COMMAND=ssh -i /home/<vm-user>/.ssh/heartbeat_write -o IdentitiesOnly=yes`;
   `ExecStart=…/python …/scripts/vm_heartbeat.py --data-dir /opt/ipo/data --beat /opt/hb/heartbeat.json`;
   then `ExecStart=/usr/bin/git -C /opt/hb commit -am beat` and `ExecStart=/usr/bin/git -C /opt/hb push`
   (the write key is scoped to the heartbeat repo only).
4. **VM systemd — keepalive** (`nice`d timer, every 30 min): `ExecStart=…/python
   …/scripts/vm_keepalive.py --data-dir /opt/ipo/data --seconds 240`. The single busy-loop pegs ONE
   vCPU; the shape is **E2.1.Micro = 1 OCPU = 2 vCPU**, so that reads **~51%** instance CPU, not 100%.
   A 240s burn every 30 min = **13.3% duty**, keeping the console CPU **p95 well over the 20% reclaim
   bar** (robust even under 5-min aggregation, ~41%/bucket). Was `--seconds 120` until 2026-07-16
   (marginal — ~20.5% under 5-min averaging); raised to 240s for margin. **Verify** on the Oracle
   console: metric `oci_computeagent/CpuUtilization`, **Statistic = P95, Interval = 1 minute, 7-day
   window** — must read ≥ 20%, with the ~50% spikes recurring every 30 min. **The reclaim rule is CPU
   p95 < 20% over 7 days** (below 20% for ~95% of the time), so periodic bursts covering ≥5% of the
   window (~8.4 h/wk) clear it — a single brief spike does not, and Mean is *not* the number to read.
   **Network is a non-lever** here (the box transmits ~0% of its ~480 Mbps cap; CPU is the only
   controllable dimension — Memory is A1-only). OCI Monitoring retains metrics **90 days**, so the full
   rolling 7-day window is always inspectable. Steady genuine fetch load does most of the work; this
   is the top-up.
5. **Desktop** — before the heartbeat ritual, `git -C <hb-clone> pull`, then
   `run_heartbeat --vm-heartbeat <hb-clone>/heartbeat.json`.
6. **HARD calendar item — Oracle console login every ≤30 days.** No script can prevent *account*-level
   reclaim; this is a manual recurring reminder you set. It is load-bearing, not optional.

### Telegram alerting & control (v3 V3-3) — off by default (dark-ships without creds); deploy runbook

The operator-facing surface of VM monitoring: it turns the `heartbeat.json` / `VmStatus` health facts
into **push alerts + interactive commands** on Telegram. Three roles, all reading the same `VmStatus`
snapshot (`vm_status.build_status`) so what you see is consistent, and **all dark-ship** — with no
`/etc/ipo/telegram.env` they are silent no-ops:

- **Health digest** — `ipo-telegram-digest.timer` → `vm_telegram_digest.py`, **4×/day at 00:00 / 06:00
  / 12:00 / 18:00 IST** (`Persistent=true`). The periodic reconciler: sends the full health snapshot
  **unconditionally** (OK *or* DEGRADED), with the alert-check's "N consecutive since HH:MM" notes.
- **State-change alerts** — `ipo-alert-check.timer` → `vm_alert_check.py`, **every 20 min**
  (`OnBootSec=3min`, `OnUnitActiveSec=20min`). The transition detector: **one** alert when a condition
  first breaks (or escalates, e.g. the Oracle-login tier), **one** when it recovers, and **nothing**
  while it stays broken (no cry-wolf; the count + since accrue for the digest). It is the **single
  writer** of `alert_state.json`; the digest only reads it.
- **Owner-only command bot** — `ipo-telegram-bot.service` → `vm_telegram_bot.py`, a **long-poll daemon**
  (`Restart=always`). Answers **`/status`** (the VM health snapshot on demand) and **`/login`** (record
  that you did the ≤30-day Oracle console login — feeds the login-staleness dimension). Commands are
  **owner-only** (chat-id checked). On start it registers the **`/` command menu** via `setMyCommands`
  (single-source `COMMANDS` in `telegram_commands.py`), so the menu appears when you type "/".

**Deploy (you provision):**

1. **Create the bot + find your chat id.** Talk to `@BotFather` → `/newbot` → copy the **bot token**.
   Message your new bot once, then read your numeric **chat id** (e.g. via `@userinfobot`, or the
   `getUpdates` API). The bot only ever talks to this one chat.
2. **Credentials file** — `/etc/ipo/telegram.env` (owner `root:root`, mode `600`, outside `/opt/ipo`,
   never committed), two lines:
   ```
   TELEGRAM_BOT_TOKEN=…
   TELEGRAM_CHAT_ID=…
   ```
3. **Three systemd units**, each with `EnvironmentFile=/etc/ipo/telegram.env` and
   `User=<vm-user>`, `WorkingDirectory=/opt/ipo`:
   - `ipo-telegram-digest.service` (`oneshot`) + `.timer` (the four `OnCalendar=… Asia/Kolkata` lines
     above, `Persistent=true`);
   - `ipo-alert-check.service` (`oneshot`) + `.timer` (`OnBootSec=3min`, `OnUnitActiveSec=20min`,
     `Persistent=true`);
   - `ipo-telegram-bot.service` (long-running, `Restart=always`), `ExecStart=…/python
     …/scripts/vm_telegram_bot.py --data-dir /opt/ipo/data`.
   Enable the two timers + the bot service (`systemctl enable --now …`). `OnFailure=` on the oneshots
   points at the alert path, so a failed digest/alert-check itself pings you.
4. **Verify:** `systemctl start ipo-telegram-digest.service` → a digest arrives; type `/status` in the
   chat → the health snapshot replies; type "/" → the command menu shows. A digest sends silently on
   HTTP 200 (a non-200/error logs a WARNING to the journal — that's how you tell a real send from a
   dark-ship).

**Redeploy after a code change:** scp the Telegram files (the `scripts/` entry points + the
`src/ipo/service/` modules on the sync list above), then restart the affected unit(s). The `/` menu
re-registers on the next `ipo-telegram-bot` restart (`getMyCommands` to confirm). **Dark-ship:** remove
or blank `telegram.env` and all three go inert — no messages, no errors.

### Forward subscription recorder (v3-DP DP-1) — piggybacks `ipo-ingest`; deploy runbook

Banks the full intraday demand book of every mainboard IPO across its open→close window, so the
close-day questions this project keeps returning to ("does the noon book differ from the 3 PM
book?") become answerable in ~6–12 months. Intraday subscription is **collect-forward-or-lose-it**:
NSE re-serves only the final book, so there is no archive to backfill from.

**It is a code + deploy change, NOT a new timer.** `ipo-ingest.service` already fetches each open
IPO's subscription every 30 min in order to score it; DP-1 makes that same response also append to
an append-only series. One fetch, two writes — zero added NSE load, and the recorder's cadence *is*
the ingest cadence.

- **VM-only by construction.** The sink is created in `run_live_ingest.py`, **not** inside
  `refresh_from_nse` — which is also the desktop's local-fallback leaf, so hooking it there would
  turn every shipped `.exe` into a recorder during a VM outage. One writer, one home.
- **Store:** `/opt/ipo/data/series/<ipo_id>.json`, one file per IPO, replaced atomically
  (`tmp` + `os.replace`). Each IPO's series is bounded (~3 days ≈ ~150 samples ≈ ~150 KB) so it
  completes rather than growing; an interrupted write can never corrupt the bank because a partial
  file is never observable at the live path. Volume ≈ **26 MB/year** at ~40 mainboard IPOs.
- **A failed fetch banks NOTHING** — never a fabricated row. (`_degrade_subscription` replays the
  prior record's numbers stamped with the prior `captured_at`; banking that would be
  indistinguishable from a real reading later.) An honest gap, visible on the health row.
- **Health:** a `Recorder` row in the existing digest fan-out — so it also reaches `/status`, the
  DEGRADED rollup, and the 20-min alert-check's break/recover transitions with their existing
  repeat-suppression, with **no second writer to `alert_state.json`**. Crucially the row separates
  *correctly idle* ("no IPO in window" — the normal state for weeks between IPOs) from *broken*
  ("IPOs in window but nothing banked", or the cycle itself not running). A row that went red for
  quiet weeks would be ignored by the time it mattered.
- **`OnFailure` is deliberately untouched** — see `operations/systemd/README.md` for why routing the
  recorder through it would make that alert contradict the digest.
- **Logs** now go to `<data-dir>/logs/engine.log` (the rotated family `service/logs.py` reads)
  rather than stderr only, so recorder events are durable and greppable on the box. Note what this
  does *not* buy: the recorder runs only on the VM, and the V3-16 debug console reads the *local*
  engine log, so these events do not appear in a desktop console. Serving them would need a `/logs`
  route on the VM read-API, which does not exist and is out of scope here.

**Deploy (you provision):**

1. `scp` the new `src/ipo/series/` package **and** the modified `data/ingest/live.py`,
   `data/sources/nse.py`, `scripts/run_live_ingest.py`, `service/vm_health.py`,
   `service/vm_status.py` (see the sync file-list above — a package missing from the box fails only
   when the unit next runs).
2. **The recorder itself needs no restart** — `ipo-ingest.service` is `Type=oneshot`, so the next
   30-min firing picks up the new code via the editable `.venv`. Same for
   `ipo-telegram-digest.service` and `ipo-alert-check.service` (both oneshot timers), so the new
   `Recorder` row appears in the digest and in alert-checking on their own.
   **BUT restart the bot:** `sudo systemctl restart ipo-telegram-bot`. It is the one
   **long-running** unit (`Restart=always`) and it imports `vm_status.build_status` at start, so
   until it restarts the `/status` command keeps serving the OLD row set — silently missing the
   `Recorder` row while the digest correctly shows it. No dependency change, no new unit, no new
   secret.
3. **Verify** after the next cycle (≤30 min):
   `ls /opt/ipo/data/series/` and `cat /opt/ipo/data/series/recorder_state.json`, then confirm the
   `Recorder` row appears in the next digest or `/status`. With no IPO currently open the honest
   expected result is `Recorder  idle — no IPO in window (0 samples banked)` — **not** an error.

**Dark-ship:** desktop and every other caller pass no sink, so this is inert everywhere except the
VM's ingest unit.

### Weekly fallback self-test (v3 V3-4) — off by default; deploy runbook

V3-1's local fallback only runs when the VM is down, so it can rot undiscovered until the day you need
it. This self-test drives the **genuine** local path on demand (only the trigger is faked — a
`VmClient` that raises `VmUnavailable` — while `refresh_from_nse` → the real `NseClient` → real NSE →
validation → write is all genuine) into a **throwaway, always-cleaned-up** store, and records a
verdict `run_heartbeat` surfaces. No manufactured outage; the VM can be up and serving.

1. **Weekly scheduled task (desktop, repo `.venv` Python).** It uses the SAME polite `NseClient` as
   the live ingest (rate limit + UA — one hit a week is trivial load):
   ```
   schtasks /Create /TN "IPO Fallback Selftest" /SC WEEKLY /D SUN /ST 09:00 /RL LIMITED /F /TR "C:\path\to\.venv\Scripts\python.exe C:\path\to\scripts\fallback_selftest.py --out C:\path\to\data_store\fallback_selftest.json"
   ```
2. **Ritual.** Add `--fallback-selftest <path>/fallback_selftest.json` to your `run_heartbeat` run. A
   FAILED scrape (feed-shape change / broken dependency) → `[STALE] local fallback - self-test FAILED
   …` and exit 1; a stale result (the weekly task stopped) → `… self-test stale … weekly test not
   running?` and exit 1; healthy → `[OK] local fallback - self-test passed 3d ago (7 records)`. Off
   unless the flag is given — ships dark.

## Appendix — kept operator scripts (what writes what)

| Script | Purpose | Writes |
|---|---|---|
| `scripts/run_ingest.py` | Ingestion pipeline (sources → merge → hygiene → store + labels) — the **seed/backfill** pipeline, NOT the live fetch | the record store |
| `scripts/run_live_ingest.py` | v3 V3-1 — the VM's **records timer**: one LIVE NSE fetch (`refresh_from_nse`, the app's exact path) into `--data-dir`; writes `ipo_records.parquet` + the genuine `ingest_state.json`. **Plus (v3, new-IPO onset trigger):** diffs pre/post-upsert `ipo_id`s and fires one immediate single-symbol context pull per genuinely new id (needs `UPSTOX_TOKEN` in its unit's environment; dark-ships without it) | `<data_dir>/ipo_records.parquet`, `<data_dir>/ingest_state.json`, + a merged `<data_dir>/context/ipo_context.json` entry per new IPO |
| `scripts/run_backfill.py` | Polite official-NSE backfill of the mainboard sample | `data/backfill/mainboard_ipos.csv` |
| `scripts/fetch_vix.py` | India VIX daily-close backfill (append-only) | `data/backfill/vix.csv` |
| `scripts/run_calibrate.py` | **Fit + gate** the calibrator (the recalibration ritual, §2) | `models/calibrator.json`, `docs/CALIBRATION.md` |
| `scripts/run_reliability_export.py` | Export the held-out OOS reliability the UI serves | `models/reliability.json` |
| `scripts/run_recalibration_check.py` | Dry-run: does a re-fit reproduce the shipped calibrator? | nothing (read-only) |
| `scripts/run_accuracy_monitor.py` | Drift monitor: recent window vs OOS baseline | nothing (prints; exit 1 on alert) |
| `scripts/run_t3_stability.py` | T+3 settlement cross-break calibration check | `docs/T3_STABILITY.md` |
| `scripts/run_heartbeat.py` | Data-source freshness heartbeat **+ stranded-listing audit** (`--data-dir`, v3 finding-④) **+ VM-liveness check** (`--vm-heartbeat`, v3 V3-3) **+ fallback self-test verdict** (`--fallback-selftest`, v3 V3-4) | nothing (prints; exit 1 if a feed is missing, a listing is overdue, the VM heartbeat is stale/degraded, **or** the fallback self-test FAILED/stale) |
| `scripts/refresh_context.py` | v3 V3-5/6/8/11 — refresh the per-IPO Upstox context cache (registrar + RHP + lot_size + isin + industry; display-only; needs `UPSTOX_TOKEN`). **Plus (v3, new-IPO onset trigger):** `refresh_one`/`merge_context`/`refresh_and_merge_one` — a single-symbol fetch + merge-write, called by `run_live_ingest.py`; `main()`'s own 3×/day full-batch overwrite is unchanged | `<data_dir>/context/ipo_context.json` (token-free) |
| `scripts/run_vm_server.py` | v3 V3-1 — the VM read-API server (GET-only `/health` `/records` `/context`; run **on** the VM behind its fetch jobs; never runs the model) | `<data_dir>/logs/vm.log` (serves records + context read-only) |
| `scripts/archive_drop.ps1` | **Retired** (v3 V3-2, superseded) — desktop drop is permanently dropped; no longer scheduled | — |
| `scripts/archive_pull.py` | **Retired** (v3 V3-2, superseded) — left in place, unused; nothing pulls into `ipo-archive` anymore | — |
| `scripts/vm_archive_snapshot.py` | v3 V3-2 (revised) — VM-side: mirror records + context into the `ipo-archive` clone (pure copy; the unit's shell step commits/pushes) | `<archive-clone>/ipo_records.parquet`, `<archive-clone>/ipo_context.json`, `<data_dir>/logs/archive_snapshot.log` |
| `scripts/vm_heartbeat.py` | v3 V3-3 — VM-side: write the liveness heartbeat + ping the dead-man's-switch monitor (dark-ship without `HC_PING_URL`) | `<channel>/heartbeat.json`, `<data_dir>/logs/heartbeat.log` |
| `scripts/vm_keepalive.py` | v3 V3-3 — VM-side: bounded CPU keepalive (anti-reclaim) + touch the marker the heartbeat checks | `<data_dir>/keepalive.marker` |
| `scripts/fallback_selftest.py` | v3 V3-4 — weekly: drive the REAL local fallback (VM up) into a throwaway store + record the verdict; run_heartbeat surfaces FAILED/stale | `<out>/fallback_selftest.json` |

*These are the only scripts retained at project close — the one-shot evidence-generators that produced
the (now-consolidated) gate docs were removed; their results live permanently in
[`docs/PROJECT_LOG.md`](../docs/PROJECT_LOG.md).*

### Dev/CI note — STANDING RULE: every code/tool pin carries an upper bound

**Every dependency in `pyproject.toml` is pinned `>=X,<next-major` — the ONLY exception is a pure
data package (`tzdata`), where you want the latest.** Reason: an unbounded pin lets a routine
`pip install -e ".[dev]"` pull a new major that **silently reddens the gate on `main` with no code
change** — the same silent-failure class this project keeps guarding against (cf. §5 / finding-④). It
has bitten this project three times (unbounded-alert growth → **mypy 2.x** → **black 26.x**), so it is
now a rule, not a case-by-case fix. When you add a dependency, add its upper bound. To adopt a new
major, do it deliberately in one pass: bump the cap, run the full gate, fix what the new major flags
(mypy: annotate; black: `black .` + commit the reformat), then commit. Notable caps:

- **`mypy>=1.9,<2`** — mypy 2.x tightened bare-generic checks.
- **`black>=24.0,<27`** — black changes its stable style yearly (26.x reformatted `logging.py` +
  `refresh_context.py`).
- **`httpx>=0.27,<1.0`** — pinned until the starlette/httpx2 TestClient cutover is handled.

### Dev note — STANDING RULE: systemd unit state is NOT a health signal

**Health is derived from `ingest_state.json` + live probes, never from systemd unit state — a
unit's `active`/`failed` status is not a truth source here.**

This is already true throughout the codebase and was, until now, recorded only as a one-line code
comment. Verified by grep: `systemctl` / `is-active` / `is-failed` / `ActiveState` appear **zero**
times across `src/` and `scripts/`. Instead, `check_ingest` judges freshness from
`IngestStateStore`'s `last_success` / `last_attempt_ok`, and the read-API row runs a real HTTP
probe — deliberately, per `vm_status.py`: *a hung app stays systemd-`active` but stops serving.*

The rule cuts both ways, and the second direction is the one that catches people:

- **`active` does not mean healthy** — the hung-but-active case above.
- **`failed` does not mean the job failed** — a unit can be made to exit non-zero to signal
  something *other* than its primary job, at which point its status lies to anyone reading it.

v3-DP DP-1 hit exactly the second case and declined it: routing the recorder's failure through
`ipo-ingest.service`'s `OnFailure` would have marked the ingest unit `failed` on a recorder hiccup
while the ingest itself had succeeded and committed — and the very next digest would have correctly
reported `✓ NSE ingest` off `ingest_state.json`. Two contradictory surfaces from one event.

Write it down here so the next session does not rediscover this by grep, and is not tempted by the
same `OnFailure` shortcut. If you need a new health signal, add a `FeedHealth` row fed by a fact the
code owns — not by asking systemd how a unit is feeling.

### Dev note — the scoring-path guard (Part I rule 1)

Every v3 change must leave the scoring path byte-identical. Two checks, run on each branch:
- **Cheap proxy:** `python scripts/check_scoring_path.py [base]` fails if a change touches anything
  under `model` / `calibration` / `features` / `core`, `models/`, or `config/` — with one reviewed
  allowlist entry, `src/ipo/core/logging.py` (a **write-only sink**, unreachable from
  `features/build.py`; verdicts proven byte-identical when it changes). The allowlist keeps the
  proxy *precise* — a guard that fires on a file it can't break trains you to override it, and then
  you override the real firing too. Add to it only with a reason.
- **Definitive:** dump verdicts on the branch vs the base and confirm **`MAX|Δprob| = 0.0`** across
  all IPOs. The proxy is a fast pre-check; this is the actual invariant.
