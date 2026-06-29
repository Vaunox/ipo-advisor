"""Protocols — the contracts every layer programs against (Ground Rule 1).

Anything with more than one implementation is defined here as a ``Protocol`` so
downstream code depends on the interface, never a concrete class. In particular
**nothing outside ``data/sources/`` imports a scraper client** — callers depend on
``DataSource`` only.

These are structural (duck-typed) and ``@runtime_checkable`` so a fake in tests
satisfies the contract without inheritance. None of these contracts includes any
order-placement method: the system is advisory only (Inviolable Rule 6).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ipo.core.types import (
    IPOFeatures,
    IPORecord,
    ListingLabel,
    PartialRecord,
    RawResponse,
    Verdict,
)


@runtime_checkable
class DataSource(Protocol):
    """One adapter per external source. The only place a source client is imported.

    ``fetch`` returns an immutably-cached, hashed raw response; ``parse`` is a pure,
    schema-validated function of that raw (re-parsing never re-fetches). A parse
    that finds a missing/off-type field must raise, not return a half-record — this
    is the source-drift tripwire (Deep Dive #1, Module 3).
    """

    name: str

    def fetch(self, ipo_id: str) -> RawResponse:
        """Return the cached, hashed raw response for ``ipo_id``."""
        ...

    def parse(self, raw: RawResponse) -> PartialRecord:
        """Parse a cached raw response into a validated partial record (pure)."""
        ...


@runtime_checkable
class Repository(Protocol):
    """Persistence boundary for IPO records and labels (Parquet, in Phase 1).

    Upserts are idempotent and keyed on ``ipo_id``: re-running an ingest never
    duplicates or silently mutates a row (Deep Dive #1, Module 3).
    """

    def upsert(self, record: IPORecord) -> None:
        """Insert or update one record, keyed on ``ipo_id`` (idempotent)."""
        ...

    def upsert_many(self, records: list[IPORecord]) -> None:
        """Insert or update many records with a single flush (idempotent)."""
        ...

    def get(self, ipo_id: str) -> IPORecord | None:
        """Return the record for ``ipo_id``, or ``None`` if absent."""
        ...

    def list_all(self) -> list[IPORecord]:
        """Return every stored record."""
        ...

    def save_labels(self, labels: list[ListingLabel]) -> None:
        """Persist the listing-label table (the supervised target)."""
        ...

    def load_labels(self) -> list[ListingLabel]:
        """Load the listing-label table (empty if none persisted)."""
        ...


@runtime_checkable
class ScoringModel(Protocol):
    """Transparent weighted baseline: features -> one raw, uncalibrated score.

    The raw score feeds the ``Calibrator`` (Layer 4). The model is interpretable:
    ``contributions`` names each feature's signed contribution so the reason
    generator can cite real values (Layer 3).
    """

    def score(self, features: IPOFeatures) -> float:
        """Return the raw (uncalibrated) score for a feature vector."""
        ...

    def contributions(self, features: IPOFeatures) -> dict[str, float]:
        """Return each feature's signed contribution to the raw score."""
        ...


@runtime_checkable
class Calibrator(Protocol):
    """Maps a raw score to a calibrated probability (calibration is SACRED).

    ``predict_proba`` must not be trusted until ``passes_reliability_gate`` is
    True on out-of-sample IPOs (Inviolable Rule 1). ``version`` pins the fitted
    artifact for determinism and reproducibility (Ground Rule 7).
    """

    version: str

    def fit(self, raw_scores: list[float], labels: list[int]) -> None:
        """Fit the calibrator on held-out (score, positive-listing) pairs."""
        ...

    def predict_proba(self, raw_score: float) -> float:
        """Return the calibrated P(positive listing) for one raw score."""
        ...

    @property
    def passes_reliability_gate(self) -> bool:
        """True once predicted-vs-actual tracks the diagonal within tolerance."""
        ...


@runtime_checkable
class Notifier(Protocol):
    """Pushes a verdict out when it crosses a threshold (Layer 5).

    Advisory only: a notifier informs the operator; it never acts on the market.
    """

    def notify(self, verdict: Verdict, *, message: str) -> None:
        """Deliver a verdict notification through the configured channel."""
        ...
