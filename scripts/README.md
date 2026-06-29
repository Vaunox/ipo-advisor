# Operational entry points

CLI entry points that wire the layers together. Added as their phases land:

- `run_ingest.py` — Phase 1 (official ingestion + labels)
- `run_backtest.py` — Phase 4 (walk-forward backtest)
- `run_calibrate.py` — Phase 4 (fit + persist the calibrator)
- `run_service.py` — Phase 6 (advisory service)

Each script is a thin shell over `src/ipo/`; production logic never lives here.
