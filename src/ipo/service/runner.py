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
from ipo.calibration.regime import NiftyRegime, VixSeries
from ipo.core.calendar import now_ist
from ipo.core.config import AppConfig, load_config
from ipo.core.interfaces import Calibrator, Notifier, Repository
from ipo.core.logging import configure_logging, get_logger
from ipo.data.ingest.state import IngestStateStore
from ipo.data.store.repository import ParquetRepository
from ipo.model.scorer import WeightedScorer
from ipo.service.api import create_app
from ipo.service.engine import VerdictEngine
from ipo.service.ipo_context import ContextStore
from ipo.service.notify import build_notifier, notify_crossings
from ipo.service.scheduler import CycleResult, ScoringScheduler
from ipo.service.transitions import TransitionStore

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Bump whenever the bundled seed store changes so an *update* refreshes a user's data dir instead of
# keeping stale records forever (provisioning otherwise never overwrites). v2 dropped the fabricated
# demo companies; a mismatch clears the store so the clean seed + live ingest rebuild it.
_SEED_VERSION = "2"

# v3 BUG 1 / Defect 1 — the shell asks for a real NSE pull on window open/focus (and via the manual
# Refresh button) by writing this command to the engine's stdin. This is a parent-only channel: the
# desktop shell spawned the process, so only it can write the pipe — the read-only HTTP API stays
# GET-only and the renderer stays incapable of making the engine act (Inviolable Rule 6 preserved
# structurally, not by policy).
_STDIN_REFRESH_COMMAND = "refresh"

# Coalesce a focus burst (Electron fires several show/focus/restore events on one reopen) into at
# most one polite pull: a stdin-triggered refresh is skipped if any ingest was ATTEMPTED within this
# window. Measured against ``last_attempt`` (not ``last_success``) so a burst is coalesced and a
# down-NSE isn't hammered, while a genuine reopen minutes later still triggers a fresh pull.
_STDIN_REFRESH_DEBOUNCE_SEC = 15.0


def _resource_root() -> Path:
    """Where the read-only artifacts (models, nifty, seed store) live.

    In a PyInstaller build the bundled data is unpacked under ``sys._MEIPASS``; from source it sits
    at the repo root. Resolving it here lets the same ``main()`` serve both dev and the packaged
    sidecar without branching on "am I frozen" at every call site.
    """
    bundle = getattr(sys, "_MEIPASS", None)
    return Path(bundle) if bundle else _REPO_ROOT


def _provision_data_dir(data_dir: Path, resource_root: Path, *, manage: bool) -> None:
    """Prepare the packaged app's writable store (versioned); a no-op in dev.

    ``manage`` is True only for the packaged app. When False (dev-from-source) this returns
    immediately — the developer owns ``data_store`` and it must never be cleared.

    When True it is **versioned**: if the stored seed version differs from ``_SEED_VERSION`` (fresh
    install, or an update that changed the shipped data) the old record store + transition log are
    cleared, so stale/demo records from an earlier install never persist across an update. Any
    bundled ``_seed/`` is then copied in; a **live-only build ships no seed**, so a mismatch simply
    clears the store and live ingestion refills it. An unchanged version keeps the user's
    live-accumulated data untouched.
    """
    if not manage:
        return

    import shutil

    data_dir.mkdir(parents=True, exist_ok=True)
    marker = data_dir / "seed_version"
    stored = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
    if stored != _SEED_VERSION:
        for name in ("ipo_records.parquet", "verdict_transitions.json"):
            (data_dir / name).unlink(missing_ok=True)
    seed = resource_root / "_seed"
    if seed.is_dir():
        for name in ("ipo_records.parquet", "verdict_transitions.json"):
            src, dst = seed / name, data_dir / name
            if src.is_file() and not dst.exists():
                shutil.copyfile(src, dst)
    marker.write_text(_SEED_VERSION, encoding="utf-8")


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
    vix_path: Path | None = None,
    calibration_report_path: Path | None = None,
    transition_store: TransitionStore | None = None,
    push_transport: Callable[[str], None] | None = None,
    refresh: Callable[[], None] | None = None,
    ingest_state: IngestStateStore | None = None,
    context_store: ContextStore | None = None,
    clock: Callable[[], datetime] = now_ist,
) -> Service:
    """Wire the layers into a running service (composition only — no new logic).

    ``transition_store`` is the durable verdict-change log (injected so tests can isolate it); it
    defaults to ``verdict_transitions.json`` under the configured data dir.

    ``ingest_state`` (v3 BUG 1 / Defect 2) is the live-ingest freshness store the ``/status``
    endpoint serves; the ``refresh`` closure records into the same instance so the served timestamp
    only ever reflects a real, successful NSE pull.
    """
    scorer = WeightedScorer(config.feature_weights, config.features)
    regime = NiftyRegime(nifty_path)
    # v2 B2: layer India VIX onto the cold-market flag when present (flag-only, weight 0).
    rc = config.features.regime
    vix = (
        VixSeries(vix_path, reference=rc.vix_reference, scale=rc.vix_scale)
        if vix_path is not None and vix_path.is_file()
        else None
    )
    transitions = transition_store or TransitionStore(
        Path(config.storage.data_dir) / "verdict_transitions.json"
    )
    engine = VerdictEngine(
        repository=repository,
        calibrator=calibrator,
        scorer=scorer,
        config=config,
        regime=regime,
        vix=vix,
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
        api=create_app(
            engine,
            calibration_report_path=calibration_report_path,
            ingest_state=ingest_state,
            context_store=context_store,
        ),
    )


def _live_refresh(
    config: AppConfig,
    repository: Repository,
    data_dir: Path,
    ingest_state: IngestStateStore | None = None,
) -> Callable[[], None] | None:
    """Build the scheduler's live-ingest refresh (NSE current issues → store), or None if disabled.

    Constructs the polite NSE client (cookie-handshake, rate-limited; robots off — NSE disallows
    ``/api``, operator-authorized public data) and returns a callback the scheduler runs each cycle.
    ``refresh_from_nse`` never raises, so a live-data hiccup degrades to the last store — and, when
    ``ingest_state`` is supplied, records that hiccup so the freshness timestamp stays honest.
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
        refresh_from_nse(repository, nse, state=ingest_state)

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
    frozen = getattr(sys, "_MEIPASS", None) is not None  # packaged app vs dev-from-source
    config = load_config(config_dir=res / "config")
    data_dir = Path(args.data_dir) if args.data_dir else Path(config.storage.data_dir)
    _provision_data_dir(data_dir, res, manage=frozen)
    # Turn the structured logger ON in the live engine (v3 A) — it exists but was only wired in the
    # batch scripts, so INFO was dropped and WARN escaped as unstructured lastResort text. Full
    # detail goes to a size-capped rotating file in the data dir (durable + greppable, esp. once the
    # VM lands); stderr stays at WARN so the desktop shell's console isn't flooded.
    configure_logging(
        config.logging.level,
        json_output=config.logging.json_output,
        file_path=data_dir / "logs" / "engine.log",
    )
    repository = ParquetRepository(data_dir)
    log = get_logger("ipo.service.runner")
    # One shared freshness store: the refresh path writes it, /status reads it (v3 BUG 1/Defect 2).
    # Only wired when live ingestion is on — so /status honestly reports live_ingest=false (and the
    # chip shows "Live", not a forever-"awaiting" timestamp) when there is no feed to be fresh from.
    ingest_state = (
        IngestStateStore(data_dir / "ingest_state.json") if config.scrape.live_ingest else None
    )
    # Display-only per-IPO Upstox context cache the Allotment tab + detail RHP link read (v3
    # V3-5/V3-6). The app only READS it — the fetch is an external, VM-runnable job
    # (scripts/refresh_context.py) writing into this same data plane. Read-only + off the scheduler
    # → severable: Upstox down never touches verdicts.
    context_store = ContextStore(data_dir / "context" / "ipo_context.json")
    service = build_service(
        config,
        repository=repository,
        calibrator=load_calibrator(res / "models" / "calibrator.json"),
        nifty_path=res / "data" / "backfill" / "nifty.csv",
        vix_path=res / "data" / "backfill" / "vix.csv",
        calibration_report_path=res / "models" / "reliability.json",
        transition_store=TransitionStore(data_dir / "verdict_transitions.json"),
        refresh=_live_refresh(config, repository, data_dir, ingest_state),
        ingest_state=ingest_state,
        context_store=context_store,
        # A logging transport so a 'push' notify channel never crashes for lack of one (the
        # user-facing alerts are the renderer's native toasts; this just journals crossings).
        push_transport=lambda message: log.info("notify_crossing", extra={"message": message}),
    )

    # The scheduler loop and the shell-triggered on-open refresh both run a cycle; a shared lock
    # serializes them so two cycles never overlap on the store (v3 BUG 1 / Defect 1).
    cycle_lock = threading.Lock()

    def loop() -> None:
        while True:
            with cycle_lock:
                service.run_cycle()
            time.sleep(service.scheduler.next_cadence_minutes() * 60)

    def stdin_refresh_loop() -> None:
        """Run a real refresh cycle when the desktop shell writes 'refresh' to our stdin.

        Debounced against the last ingest *attempt* so a focus burst coalesces into one polite pull
        and a failing NSE isn't hammered. On EOF (the shell exited / closed the pipe) the loop ends.
        Guarded by ``cycle_lock`` so it never races the scheduler loop.
        """
        stream = sys.stdin
        if stream is None:  # no stdin (e.g. detached) → on-open refresh simply unavailable
            return
        for line in stream:
            if line.strip() != _STDIN_REFRESH_COMMAND:
                continue
            last = ingest_state.current().last_attempt if ingest_state is not None else None
            if last is not None:
                age = (now_ist() - last).total_seconds()
                if age < _STDIN_REFRESH_DEBOUNCE_SEC:
                    log.info("stdin_refresh_debounced", extra={"age_sec": round(age, 1)})
                    continue
            log.info("stdin_refresh_triggered")
            with cycle_lock:
                service.run_cycle()

    threading.Thread(target=loop, daemon=True).start()
    threading.Thread(target=stdin_refresh_loop, daemon=True).start()
    uvicorn.run(service.api, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
