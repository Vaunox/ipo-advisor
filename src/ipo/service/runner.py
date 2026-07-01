"""Service composition root + entrypoint (Phase 6 step 6) — the wire-up, GATE 6.

Composition only. It wires the already-proven layers — Repository + Calibrator + ScoringModel
+ NiftyRegime → VerdictEngine → ScoringScheduler + Notifier + the read-only API — into one
running service. **No new scoring or notify logic lives here**; the five invariants are
inherited and re-proven end-to-end at GATE 6:

1. point-in-time / as-of-now (engine + regime),
2. calibration-sacred: ``market_regime`` is flag-only (weight 0) — the probability never moves,
3. the probability stays gated on the reliability gate (no number until blessed),
4. idempotent cycles (no duplicate work or notifications),
5. advisory-only: the API is read-only and the notifier alerts; nothing places an order.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI

from ipo.calibration.calibrate import load_calibrator
from ipo.calibration.regime import NiftyRegime
from ipo.core.calendar import now_ist
from ipo.core.config import AppConfig, load_config
from ipo.core.interfaces import Calibrator, Notifier, Repository
from ipo.data.store.repository import ParquetRepository
from ipo.model.scorer import WeightedScorer
from ipo.service.api import create_app
from ipo.service.engine import VerdictEngine
from ipo.service.notify import build_notifier, notify_crossings
from ipo.service.scheduler import CycleResult, ScoringScheduler

_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class Service:
    """The composed advisory service: engine + scheduler + notifier + API, sharing one engine."""

    config: AppConfig
    engine: VerdictEngine
    scheduler: ScoringScheduler
    notifier: Notifier
    api: FastAPI

    def run_cycle(self) -> tuple[CycleResult, list[str]]:
        """One composed cycle: (ingest via the scheduler's refresh) → score → notify crossings.

        Returns the cycle and the ipo_ids alerted (APPLY crossings). Idempotent: a second cycle
        over unchanged state returns the same verdicts and alerts nothing.
        """
        cycle = self.scheduler.run_cycle()
        alerted = notify_crossings(cycle, self.notifier, self.config)
        return cycle, alerted


def build_service(
    config: AppConfig,
    *,
    repository: Repository,
    calibrator: Calibrator,
    nifty_path: Path,
    calibration_report_path: Path | None = None,
    push_transport: Callable[[str], None] | None = None,
    refresh: Callable[[], None] | None = None,
    clock: Callable[[], datetime] = now_ist,
) -> Service:
    """Wire the layers into a running service (composition only — no new logic)."""
    scorer = WeightedScorer(config.feature_weights, config.features)
    regime = NiftyRegime(nifty_path)
    engine = VerdictEngine(
        repository=repository,
        calibrator=calibrator,
        scorer=scorer,
        config=config,
        regime=regime,
        clock=clock,
    )
    notifier = build_notifier(config, push_transport=push_transport)
    scheduler = ScoringScheduler(source=engine, config=config, refresh=refresh, clock=clock)
    return Service(
        config=config,
        engine=engine,
        scheduler=scheduler,
        notifier=notifier,
        api=create_app(engine, calibration_report_path=calibration_report_path),
    )


def main() -> None:  # pragma: no cover - runtime entrypoint (live loop + server)
    """Build the service from config + artifacts and run it (scheduler loop + API server)."""
    import threading
    import time

    import uvicorn

    config = load_config()
    service = build_service(
        config,
        repository=ParquetRepository(Path(config.storage.data_dir)),
        calibrator=load_calibrator(_REPO_ROOT / "models" / "calibrator.json"),
        nifty_path=_REPO_ROOT / "data" / "backfill" / "nifty.csv",
        calibration_report_path=_REPO_ROOT / "models" / "reliability.json",
    )

    def loop() -> None:
        while True:
            service.run_cycle()
            time.sleep(service.scheduler.next_cadence_minutes() * 60)

    threading.Thread(target=loop, daemon=True).start()
    uvicorn.run(service.api, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
