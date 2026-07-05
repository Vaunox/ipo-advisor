# Operational entry points

Thin CLI shells over `src/ipo/` (production logic never lives here). These are the scripts retained
at project close; **how and when to run them is documented in [`operations/README.md`](../operations/README.md)**
— the maintenance manual. The one-shot evidence-generators that produced the (now-consolidated) gate
docs were removed; their results live permanently in [`docs/PROJECT_LOG.md`](../docs/PROJECT_LOG.md).

## Core data + calibration loop
- `run_ingest.py` — ingestion pipeline (sources → merge → hygiene → store + labels)
- `run_backfill.py` — polite official-NSE backfill → `data/backfill/mainboard_ipos.csv`
- `fetch_vix.py` — India VIX daily-close backfill → `data/backfill/vix.csv`
- `run_calibrate.py` — fit + gate the calibrator → `models/calibrator.json` + `docs/CALIBRATION.md`
- `run_reliability_export.py` — held-out OOS reliability → `models/reliability.json`

## A4 operator rituals (occasional, read-mostly)
- `run_recalibration_check.py` — dry-run: does a re-fit reproduce the shipped calibrator? (writes nothing)
- `run_accuracy_monitor.py` — verdict-accuracy drift monitor vs the OOS baseline
- `run_t3_stability.py` — T+3 settlement cross-break calibration check → `docs/T3_STABILITY.md`
- `run_heartbeat.py` — data-source freshness heartbeat
