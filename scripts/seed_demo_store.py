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

from ipo.core.calendar import now_ist
from ipo.core.config import load_config
from ipo.core.constants import IST
from ipo.core.types import IPORecord, Segment, SubscriptionPoint
from ipo.data.store.repository import ParquetRepository

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


def _upcoming_records(captured: datetime) -> list[IPORecord]:
    """Open / upcoming issues (book not yet closed) so the calendar is non-empty.

    Dated relative to 2026-07-02 (the demo 'today'): one live, one whose anchor lands
    tomorrow, one further out — spanning below-peer, in-line, and rich valuations.
    """
    green_prog = (
        SubscriptionPoint(
            asof=datetime(2026, 7, 1, 17, 0, tzinfo=IST),
            qib=0.38,
            nii=1.15,
            retail=2.05,
            overall=1.05,
        ),
    )
    return [
        IPORecord(
            ipo_id="greenspark-2026",
            name="Greenspark Energy Ltd",
            segment=Segment.MAINBOARD,
            price_band_low=480,
            price_band_high=505,
            lot_size=29,
            issue_size_cr=1850,
            ofs_fraction=0.35,
            open_date=date(2026, 7, 1),
            close_date=date(2026, 7, 3),
            issue_pe=32.0,
            peer_median_pe=38.0,
            subscription_progression=green_prog,
            captured_at=captured,
        ),
        IPORecord(
            ipo_id="novacore-2026",
            name="NovaCore Semiconductors Ltd",
            segment=Segment.MAINBOARD,
            price_band_low=720,
            price_band_high=760,
            lot_size=19,
            issue_size_cr=3200,
            ofs_fraction=0.10,
            open_date=date(2026, 7, 4),
            close_date=date(2026, 7, 8),
            issue_pe=44.0,
            peer_median_pe=41.0,
            captured_at=captured,
        ),
        IPORecord(
            ipo_id="helioswind-2026",
            name="Helios Wind Infra Ltd",
            segment=Segment.MAINBOARD,
            price_band_low=210,
            price_band_high=222,
            lot_size=67,
            issue_size_cr=640,
            ofs_fraction=0.80,
            open_date=date(2026, 7, 9),
            close_date=date(2026, 7, 11),
            issue_pe=55.0,
            peer_median_pe=30.0,
            captured_at=captured,
        ),
    ]


def main() -> None:
    config = load_config()
    data_dir = _REPO_ROOT / config.storage.data_dir
    repo = ParquetRepository(data_dir)

    existing = repo.list_all()
    enriched = [_enrich(r) for r in existing]
    upcoming = _upcoming_records(now_ist())
    repo.upsert_many(enriched + upcoming)

    total = repo.list_all()
    print(f"demo store at {data_dir / 'ipo_records.parquet'}")
    print(f"  enriched {len(enriched)} existing record(s); {len(upcoming)} open/upcoming added")
    print(f"  total records: {len(total)}")
    for r in sorted(total, key=lambda x: x.close_date):
        prog = len(r.subscription_progression) if r.subscription_progression else 0
        print(
            f"    {r.ipo_id:<20} close {r.close_date}  overall={r.overall_sub}  "
            f"sNII={r.nii_small_sub}  bNII={r.nii_big_sub}  prog_pts={prog}"
        )


if __name__ == "__main__":
    main()
