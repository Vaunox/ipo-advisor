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

import sys
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
from ipo.core.logging import get_logger
from ipo.data.store.repository import ParquetRepository
from ipo.model.scorer import WeightedScorer
from ipo.service.api import create_app
from ipo.service.engine import VerdictEngine
from ipo.service.notify import build_notifier, notify_crossings
from ipo.service.scheduler import CycleResult, ScoringScheduler
from ipo.service.transitions import TransitionStore

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _resource_root() -> Path:
    """Where the read-only artifacts (models, nifty, seed store) live.

    In a PyInstaller build the bundled data is unpacked under ``sys._MEIPASS``; from source it sits
    at the repo root. Resolving it here lets the same ``main()`` serve both dev and the packaged
    sidecar without branching on "am I frozen" at every call site.
    """
    bundle = getattr(sys, "_MEIPASS", None)
    return Path(bundle) if bundle else _REPO_ROOT


def _provision_data_dir(data_dir: Path, resource_root: Path) -> None:
    """First-run seed: copy the bundled demo store into the writable data dir if it is empty.

    The packaged app ships a curated sample store as a read-only resource (``_seed/``); on first
    launch we copy it into the user-writable data dir so the app opens with content. Existing data
    is never overwritten, so this is a no-op on every subsequent launch and in dev.
    """
    import shutil

    data_dir.mkdir(parents=True, exist_ok=True)
    seed = resource_root / "_seed"
    if not seed.is_dir():
        return
    for name in ("ipo_records.parquet", "verdict_transitions.json"):
        src, dst = seed / name, data_dir / name
        if src.is_file() and not dst.exists():
            shutil.copyfile(src, dst)


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
    transition_store: TransitionStore | None = None,
    push_transport: Callable[[str], None] | None = None,
    refresh: Callable[[], None] | None = None,
    clock: Callable[[], datetime] = now_ist,
) -> Service:
    """Wire the layers into a running service (composition only — no new logic).

    ``transition_store`` is the durable verdict-change log (injected so tests can isolate it); it
    defaults to ``verdict_transitions.json`` under the configured data dir.
    """
    scorer = WeightedScorer(config.feature_weights, config.features)
    regime = NiftyRegime(nifty_path)
    transitions = transition_store or TransitionStore(
        Path(config.storage.data_dir) / "verdict_transitions.json"
    )
    engine = VerdictEngine(
        repository=repository,
        calibrator=calibrator,
        scorer=scorer,
        config=config,
        regime=regime,
        transitions=transitions,
        clock=clock,
    )
    notifier = build_notifier(config, push_transport=push_transport)
    scheduler = ScoringScheduler(
        source=engine,
        config=config,
        refresh=refresh,
        on_transition=transitions.record,
        initial_last=transitions.latest_by_ipo(),
        clock=clock,
    )
    return Service(
        config=config,
        engine=engine,
        scheduler=scheduler,
        notifier=notifier,
        api=create_app(engine, calibration_report_path=calibration_report_path),
    )


def _live_refresh(
    config: AppConfig, repository: Repository, data_dir: Path
) -> Callable[[], None] | None:
    """Build the scheduler's live-ingest refresh (NSE current issues → store), or None if disabled.

    Constructs the polite NSE client (cookie-handshake, rate-limited; robots off — NSE disallows
    ``/api``, operator-authorized public data) and returns a callback the scheduler runs each cycle.
    ``refresh_from_nse`` never raises, so a live-data hiccup degrades to the last store.
    """
    if not config.scrape.live_ingest:
        return None

    from ipo.data.ingest.live import refresh_from_nse
    from ipo.data.sources.base import PoliteClient, RawCache
    from ipo.data.sources.nse import NseClient

    client = PoliteClient(
        user_agent=config.scrape.user_agent,
        rate_limit_per_sec=config.scrape.rate_limit_per_sec,
        backoff_factor=config.scrape.backoff_factor,
        max_retries=config.scrape.max_retries,
        respect_robots=False,
    )
    nse = NseClient(client, RawCache(root=data_dir / "raw_cache"))

    def refresh() -> None:
        refresh_from_nse(repository, nse)

    return refresh


def main() -> None:  # pragma: no cover - runtime entrypoint (live loop + server)
    """Build the service from config + artifacts and run it (scheduler loop + API server).

    ``--port`` / ``--host`` let the desktop shell spawn the engine on a free port it picked (never
    a hardcoded port that could collide). Bound to 127.0.0.1 by default — the sidecar is local only.
    """
    import argparse
    import threading
    import time

    import uvicorn

    parser = argparse.ArgumentParser(description="Run the IPO Advisor engine (API + scheduler).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--data-dir",
        default=None,
        help="writable directory for the record store + verdict-transition log "
        "(the desktop shell passes its per-user data dir; defaults to the configured data_dir)",
    )
    args = parser.parse_args()

    # Resolve read-only artifacts (config, models, nifty, seed) from the bundle when frozen, the
    # repo root otherwise — so feature weights/thresholds come from the SAME config the seed used,
    # not the empty defaults (a missing config silently changes verdicts).
    res = _resource_root()
    config = load_config(config_dir=res / "config")
    data_dir = Path(args.data_dir) if args.data_dir else Path(config.storage.data_dir)
    _provision_data_dir(data_dir, res)
    repository = ParquetRepository(data_dir)
    service = build_service(
        config,
        repository=repository,
        calibrator=load_calibrator(res / "models" / "calibrator.json"),
        nifty_path=res / "data" / "backfill" / "nifty.csv",
        calibration_report_path=res / "models" / "reliability.json",
        transition_store=TransitionStore(data_dir / "verdict_transitions.json"),
        refresh=_live_refresh(config, repository, data_dir),
        # A logging transport so a 'push' notify channel never crashes for lack of one (the
        # user-facing alerts are the renderer's native toasts; this just journals crossings).
        push_transport=lambda message: get_logger("ipo.service.runner").info(
            "notify_crossing", extra={"message": message}
        ),
    )

    def loop() -> None:
        while True:
            service.run_cycle()
            time.sleep(service.scheduler.next_cadence_minutes() * 60)

    threading.Thread(target=loop, daemon=True).start()
    uvicorn.run(service.api, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
