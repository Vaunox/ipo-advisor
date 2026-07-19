# Committed reference copies of the VM's systemd units

**These are reference copies, not the source of truth.** The live units are the ones in
`/etc/systemd/system/` on the VM. Nothing deploys from this directory — it exists so the repo
finally *describes* the running box.

## Why this directory exists

Building v3-DP DP-1 surfaced **three** on-box realities that appeared in no repo file:

1. **The live-ingest unit had no name anywhere in the repo.** `operations/README.md` referred to it
   only as "the 30-min records timer" while naming every other unit (`ipo-context.timer`,
   `ipo-alert-check.timer`, …). It is `ipo-ingest.timer` / `ipo-ingest.service`. Establishing that
   required an SSH session, and the ambiguity had already misled planning once — the risk being that
   it might have pointed at `run_ingest.py` (the curated seed pipeline) rather than
   `run_live_ingest.py` (the live NSE path). It does not; the `ExecStart` below is the proof.
2. **`ipo-ingest.service.d/environment.conf` was already applied** while the runbook still listed
   adding it as an outstanding step.
3. **`ipo-ingest.service.d/onfailure.conf` existed and was documented nowhere.** A whole design
   option (routing DP-1's recorder alert through systemd's `OnFailure`) was evaluated against a repo
   that gave no hint this mechanism existed — the first analysis concluded "no immediate alert path
   exists", which was true of the Python code and false of the box.

Each was a case of source not reflecting reality, found by looking at the box rather than the repo.
Committing the units is the durable fix.

## Keeping these honest

A stale reference copy is worse than none — it looks authoritative. When a unit changes on the VM,
update the copy here in the same change. To verify drift:

```bash
systemctl cat ipo-ingest.timer ipo-ingest.service
```

## `OnFailure` — deliberately NOT overloaded (v3-DP DP-1)

`ipo-ingest.service` carries `OnFailure=ipo-telegram-alert@%n.service`, which sends a **fixed**
message whose only variable is the unit name:

```
WARN: %i errored (systemd OnFailure)
```

DP-1 considered making the recorder's failure ride this path for a truly immediate alert, and
**rejected it**. The template cannot say "the recorder leg failed but the ingest itself succeeded",
so one recorder hiccup would produce two *contradicting* surfaces at once: this alert claiming
`ipo-ingest.service errored`, and the very next Telegram digest correctly reporting `✓ NSE ingest`
healthy off `ingest_state.json`. An operator reconciling a false alarm against a true digest
mid-incident is exactly the "a surface must never lie" failure this project guards against.

The recorder's health therefore goes entirely through its own `Recorder` row in the existing digest
fan-out (≤20-min latency, inheriting repeat-suppression and recovery). `OnFailure` keeps doing its
one honest job: firing when the ingest *genuinely* fails. **Do not overload it.**
