"""Seed / enrich the curated demo store the desktop app serves.

The desktop sidecar reads ``data_store/ipo_records.parquet`` — a small, curated set of
representative mainboard IPOs used to demonstrate the app end-to-end. This script is the
reproducible source of that store. It is **idempotent** and keyed on ``ipo_id``: it

  1. enriches every existing record with the NII split (sNII / bNII), the
     reserved-portion-weighted overall subscription, and a running demand-progression
     series (all as-of / at-close facts — display-only, never fed to a feature), and
  2. adds a handful of open / upcoming issues (book not yet closed) so the Upcoming
     calendar has content and the engine's honest INSUFFICIENT_SIGNAL abstention is
     visible pre-close.

It never touches verdicts, weights, or the calibrator — only the display-context data on
the record. Re-running it is safe (deterministic upserts).

    python -m scripts.seed_demo_store        # enrich in place + add upcoming
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from ipo.calibration.calibrate import load_calibrator
from ipo.calibration.regime import NiftyRegime
from ipo.core.config import AppConfig, load_config
from ipo.core.constants import IST
from ipo.core.types import IPORecord, SubscriptionPoint, VerdictType
from ipo.data.store.repository import ParquetRepository
from ipo.model.scorer import WeightedScorer
from ipo.service.engine import VerdictEngine
from ipo.service.transitions import TransitionStore, VerdictTransition

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Reserved-portion weights for a typical book-built mainboard issue (QIB 50 / NII 15 /
# Retail 35). Used only to synthesize a plausible aggregate for demo records.
_W_QIB, _W_NII, _W_RETAIL = 0.50, 0.15, 0.35


def _overall(qib: float | None, nii: float | None, retail: float | None) -> float | None:
    """Reserved-portion-weighted overall subscription (None if any leg is missing)."""
    if qib is None or nii is None or retail is None:
        return None
    return round(_W_QIB * qib + _W_NII * nii + _W_RETAIL * retail, 2)


def _progression(record: IPORecord) -> tuple[SubscriptionPoint, ...] | None:
    """A per-day cumulative-demand series ramping to the record's final multiples.

    Demand builds slowly then surges on the closing day (the well-known IPO pattern), so
    the last point equals the stored finals exactly — the sparkline is consistent with the
    headline numbers, never a second source of truth.
    """
    if record.qib_sub is None or record.nii_sub is None or record.retail_sub is None:
        return None
    n_days = (record.close_date - record.open_date).days + 1
    n_days = max(n_days, 1)
    points: list[SubscriptionPoint] = []
    for i in range(n_days):
        # Late-surge curve; frac == 1.0 exactly on the final day.
        frac = ((i + 1) / n_days) ** 2.2
        day = date.fromordinal(record.open_date.toordinal() + i)
        asof = datetime(day.year, day.month, day.day, 17, 0, tzinfo=IST)
        qib = round(record.qib_sub * frac, 2)
        nii = round(record.nii_sub * frac, 2)
        retail = round(record.retail_sub * frac, 2)
        points.append(
            SubscriptionPoint(
                asof=asof, qib=qib, nii=nii, retail=retail, overall=_overall(qib, nii, retail)
            )
        )
    return tuple(points)


def _enrich(record: IPORecord) -> IPORecord:
    """Add sNII / bNII / overall / progression to a record (idempotent, deterministic)."""
    nii = record.nii_sub
    # bNII (>10L) runs hotter than sNII (<=10L) on well-received issues; both track the
    # combined NII the store already holds. Synthetic split for the demo store only.
    nii_small = round(nii * 0.82, 2) if nii is not None else None
    nii_big = round(nii * 1.24, 2) if nii is not None else None
    return record.model_copy(
        update={
            "nii_small_sub": (
                record.nii_small_sub if record.nii_small_sub is not None else nii_small
            ),
            "nii_big_sub": record.nii_big_sub if record.nii_big_sub is not None else nii_big,
            "overall_sub": (
                record.overall_sub
                if record.overall_sub is not None
                else _overall(record.qib_sub, record.nii_sub, record.retail_sub)
            ),
            "subscription_progression": record.subscription_progression or _progression(record),
        }
    )


# Real-company historical examples kept for the History/accountability tab (illustrative sample
# figures). Everything else in the old demo blob — the fabricated upcoming companies and the
# deferred-demo placeholder — is dropped; live NSE ingestion supplies real current IPOs.
_REAL_HISTORICAL = frozenset(
    {"zomato-2021", "nykaa-2021", "paytm-2021", "lic-2022", "tatatech-2023", "spectrum-sme-2023"}
)


def _seed_transitions(repo: ParquetRepository, config: AppConfig, data_dir: Path) -> int:
    """Backfill the (gitignored) verdict-transition log with each resolved IPO's close-time event.

    The engine abstains (INSUFFICIENT_SIGNAL) while a book is open and emits its verdict once the
    book closes, so the one honest transition per historical IPO is INSUFFICIENT_SIGNAL -> final,
    stamped at the engine's own decision clock (close EOD). The ``to_verdict`` and probability are
    taken from ``engine.verdict_for`` so the log can never disagree with the live verdict — this
    is a record of a real emission, not a fabricated intra-book path. Deterministic full rewrite.
    """
    engine = VerdictEngine(
        repository=repo,
        calibrator=load_calibrator(_REPO_ROOT / "models" / "calibrator.json"),
        scorer=WeightedScorer(config.feature_weights, config.features),
        config=config,
        regime=NiftyRegime(_REPO_ROOT / "data" / "backfill" / "nifty.csv"),
    )
    path = data_dir / "verdict_transitions.json"
    path.unlink(missing_ok=True)  # deterministic: rebuild from scratch
    store = TransitionStore(path)
    count = 0
    for record in sorted(repo.list_all(), key=lambda r: r.close_date):
        if record.listing_date is None:  # still open / upcoming — no resolution yet
            continue
        verdict = engine.verdict_for(record)
        if verdict.verdict is VerdictType.INSUFFICIENT_SIGNAL:  # never resolved (deferred)
            continue
        store.record(
            VerdictTransition(
                ipo_id=record.ipo_id,
                asof=engine.decision_asof(record),
                from_verdict=VerdictType.INSUFFICIENT_SIGNAL,
                to_verdict=verdict.verdict,
                probability=verdict.probability,
                crossed_into_apply=verdict.verdict is VerdictType.APPLY,
            )
        )
        count += 1
    return count


def main() -> None:
    config = load_config()
    data_dir = _REPO_ROOT / config.storage.data_dir
    repo = ParquetRepository(data_dir)

    # Keep only the real-company historical examples (for the History/accountability tab); drop the
    # fabricated "upcoming" demos and the deferred-demo placeholder. The running app ingests real
    # current IPOs live (ipo.data.ingest.live), so NO fabricated companies ship.
    kept = [_enrich(r) for r in repo.list_all() if r.ipo_id in _REAL_HISTORICAL]

    # Rewrite the store from scratch so dropped records are actually removed (upsert never deletes).
    parquet = data_dir / "ipo_records.parquet"
    parquet.unlink(missing_ok=True)
    repo = ParquetRepository(data_dir)
    repo.upsert_many(kept)
    n_transitions = _seed_transitions(repo, config, data_dir)

    total = repo.list_all()
    print(f"demo store at {parquet}")
    print(f"  kept {len(kept)} real historical example(s); fabricated/upcoming dropped")
    print(f"  total records: {len(total)}; seeded {n_transitions} verdict transition(s)")
    for r in sorted(total, key=lambda x: x.close_date):
        prog = len(r.subscription_progression) if r.subscription_progression else 0
        print(
            f"    {r.ipo_id:<20} close {r.close_date}  overall={r.overall_sub}  "
            f"sNII={r.nii_small_sub}  bNII={r.nii_big_sub}  prog_pts={prog}"
        )


if __name__ == "__main__":
    main()
