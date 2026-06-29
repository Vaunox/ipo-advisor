"""GMP source layer — multi-source reconciliation of a noisy signal (Deep Dive #5).

Grey-market premium is the model's most-weighted feature and least-trustworthy data:
unofficial, no archive, and sources disagree. This module turns raw per-source GMP
points into a single, confidence-flagged series the feature layer can use, and
detects the spike-then-collapse manipulation pattern that feeds the kill-flag.

The reconciler is shaped to ingest the common tracker-aggregator format (e.g.
ipoalerts' ``gmp`` object: ``sources:[{name, gmpPrice}]`` plus a median) — so a live
feed plugs straight in. Historical reconstruction (the hard, deferred part) produces
the same ``GMPPoint`` shape, whatever its origin (paid archive, scrape, or operator CSV).

Point-in-time: only points dated at or before the decision clock may inform a
feature (Deep Dive #4 §B) — enforced downstream in ``features.gmp``.
"""

from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol, runtime_checkable

from ipo.core.config import GmpConfig
from ipo.features.gmp import GmpQuote
from ipo.features.normalize import winsorize


@dataclass(frozen=True)
class GMPPoint:
    """One grey-market quote: a rupee premium on a date, from a named source."""

    on: date
    value: float
    source: str


@dataclass(frozen=True)
class ReconciledPoint:
    """A single per-day GMP after reconciling sources, with a confidence flag."""

    on: date
    value: float  # median across sources (robust to one outlier)
    n_sources: int
    divergence: float  # (max - min) across sources for the day
    low_confidence: bool


@runtime_checkable
class GMPHistory(Protocol):
    """A source of per-IPO GMP points (live tracker, paid archive, scrape, or CSV)."""

    def series(self, ipo_id: str) -> list[GMPPoint]:
        """Return all GMP points known for ``ipo_id`` (any sources, any dates)."""
        ...


def reconcile(points: list[GMPPoint], config: GmpConfig) -> list[ReconciledPoint]:
    """Reconcile per-source points into one confidence-flagged series per day.

    Uses the **median** across sources for the level (robust to one manipulated
    quote); flags a day **low-confidence** when sources diverge by more than the
    configured band (Deep Dive #5, Module B). Values are winsorized first so a
    single absurd print cannot move a verdict.
    """
    by_day: dict[date, list[float]] = defaultdict(list)
    for p in points:
        by_day[p.on].append(winsorize(p.value, config.winsor_min, config.winsor_max))

    series: list[ReconciledPoint] = []
    for day in sorted(by_day):
        values = by_day[day]
        median = float(statistics.median(values))
        divergence = max(values) - min(values)
        # Low confidence if the spread exceeds the band as a fraction of |median|.
        band = (
            config.divergence_band_frac * abs(median)
            if median != 0
            else config.divergence_band_frac
        )
        series.append(
            ReconciledPoint(
                on=day,
                value=median,
                n_sources=len(values),
                divergence=divergence,
                low_confidence=divergence > band,
            )
        )
    return series


def detect_spike_collapse(series: list[ReconciledPoint], config: GmpConfig) -> bool:
    """True if GMP peaked then collapsed by more than the configured fraction.

    The known manipulation pattern (Deep Dive #5, Module C): a high opening GMP that
    fades. Feeds the GMP-collapse kill-flag, not just the slope feature.
    """
    if len(series) < 2:
        return False
    peak = max(p.value for p in series)
    last = series[-1].value
    if peak <= 0:
        return False
    return (peak - last) / peak > config.collapse_drop_frac


def has_sufficient_coverage(series: list[ReconciledPoint], asof: date, config: GmpConfig) -> bool:
    """True if enough confident GMP days exist at/before ``asof`` to trust the feature.

    Below the coverage floor (or all points low-confidence) the GMP feature is treated
    as missing, pushing the record toward ``INSUFFICIENT_SIGNAL`` rather than a
    confident-but-blind GMP (Deep Dive #5, open questions).
    """
    usable = [p for p in series if p.on <= asof and not p.low_confidence]
    return len(usable) >= config.min_coverage_days


def to_quotes(series: list[ReconciledPoint]) -> list[GmpQuote]:
    """Bridge reconciled points to the ``GmpQuote`` series the feature layer consumes."""
    return [GmpQuote(on=p.on, premium=p.value) for p in series]


def from_aggregator_rows(ipo_id: str, rows: list[dict[str, object]]) -> list[GMPPoint]:
    """Build points from an aggregator's per-day source rows (e.g. ipoalerts' format).

    Each row is ``{"date": ISO, "sources": [{"name": str, "gmpPrice": number}, ...]}``.
    Flattening to per-source ``GMPPoint``s lets ``reconcile`` apply the median itself
    (so the policy is ours, not the vendor's).
    """
    points: list[GMPPoint] = []
    for row in rows:
        raw_day = str(row.get("date", ""))
        try:
            day = date.fromisoformat(raw_day[:10])
        except ValueError:
            continue
        sources = row.get("sources", [])
        if isinstance(sources, list):
            for s in sources:
                if isinstance(s, dict) and "gmpPrice" in s:
                    points.append(
                        GMPPoint(on=day, value=float(s["gmpPrice"]), source=str(s.get("name", "?")))
                    )
    return points


class CsvGmpHistory:
    """A ``GMPHistory`` backed by a curated CSV (the deferred-historical / operator path).

    Columns: ``ipo_id, date, value, source``. This is how reconstructed historical GMP
    (paid archive export, scrape, or hand-curation) enters the re-calibration gate.
    """

    def __init__(self, csv_path: Path) -> None:
        """Load and index GMP points by ``ipo_id`` from the CSV."""
        self._by_ipo: dict[str, list[GMPPoint]] = defaultdict(list)
        if not csv_path.is_file():
            return
        with csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                try:
                    self._by_ipo[row["ipo_id"]].append(
                        GMPPoint(
                            on=date.fromisoformat(row["date"]),
                            value=float(row["value"]),
                            source=row.get("source", "csv"),
                        )
                    )
                except (KeyError, ValueError):
                    continue

    def series(self, ipo_id: str) -> list[GMPPoint]:
        """Return the GMP points for ``ipo_id`` (empty if none)."""
        return list(self._by_ipo.get(ipo_id, []))
