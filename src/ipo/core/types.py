"""Canonical typed data models for the advisor.

Every field that is time-sensitive carries (directly or via the record) the
timestamp at which it was true, so point-in-time correctness (Inviolable Rule 2)
is enforceable downstream. Models validate at construction — invalid data fails
loudly and early (Ground Rule 7), never silently propagating a bad record.

The shapes here follow Deep Dive #1 (the canonical ``IPORecord`` and label) and
the Layer-2/3 output contracts in the blueprint.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Segment(StrEnum):
    """Listing segment. SME is excluded or hard-penalized upstream (Locked decision)."""

    MAINBOARD = "mainboard"
    SME = "sme"


class VerdictType(StrEnum):
    """The four — and only four — verdicts the engine may emit.

    ``INSUFFICIENT_SIGNAL`` is the honest abstention: the engine never fabricates a
    number when a critical feature is missing or the book is not closed (Rule 3).
    """

    APPLY = "APPLY"
    MARGINAL = "MARGINAL"
    SKIP = "SKIP"
    INSUFFICIENT_SIGNAL = "INSUFFICIENT_SIGNAL"


class _Frozen(BaseModel):
    """Base for immutable, strictly-validated value objects."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class AnchorAllotment(_Frozen):
    """One anchor-investor allotment line, filed pre-listing.

    Feeds the 0..1 anchor-quality feature (Layer 2). Lock-in length and the
    quality/marquee nature of the investors are the signal.
    """

    investor: str
    amount_cr: float = Field(ge=0)
    lock_in_days: int = Field(ge=0)


class RawResponse(_Frozen):
    """An immutably-cached raw source response (Deep Dive #1, Module 3).

    Parsing is a pure function of this object; re-parsing never re-fetches. The
    content hash is the cache key and the source-drift tripwire.
    """

    source: str
    url: str
    fetched_at: datetime
    content: str
    content_hash: str


class IPORecord(_Frozen):
    """The canonical, point-in-time record for one IPO (Deep Dive #1, Module 1).

    ``ipo_id`` is stable across the lifecycle (pre-issue -> subscription ->
    listing) so incremental upserts never duplicate a row. ``close_date`` is the
    as-of anchor for every decision-time feature. The label fields
    (``listing_open`` / ``listing_close``) are filled only post-listing and must
    never be read by a feature (Inviolable Rule 2).
    """

    ipo_id: str
    name: str
    segment: Segment

    price_band_low: float = Field(gt=0)
    price_band_high: float = Field(gt=0)
    lot_size: int = Field(gt=0)
    issue_size_cr: float = Field(gt=0)
    ofs_fraction: float | None = Field(default=None, ge=0, le=1)

    open_date: date
    close_date: date  # as-of anchor for decision-time features
    listing_date: date | None = None

    # Subscription multiples, captured as of close_date EOD.
    qib_sub: float | None = Field(default=None, ge=0)
    nii_sub: float | None = Field(default=None, ge=0)
    retail_sub: float | None = Field(default=None, ge=0)

    # Valuation / structure.
    issue_pe: float | None = None
    peer_median_pe: float | None = None  # None if "no listed peers" declared
    anchor_book: list[AnchorAllotment] | None = None
    promoter_litigation: bool = False

    # Label (post-listing only — never an input to a feature).
    listing_open: float | None = Field(default=None, gt=0)
    listing_close: float | None = Field(default=None, gt=0)

    # Provenance.
    captured_at: datetime
    source_hashes: dict[str, str] = Field(default_factory=dict)

    @property
    def issue_price(self) -> float:
        """Cut-off price retail applies at — the price-band top (Deep Dive #1)."""
        return self.price_band_high

    @model_validator(mode="after")
    def _check_band_and_dates(self) -> IPORecord:
        if self.price_band_high < self.price_band_low:
            raise ValueError("price_band_high must be >= price_band_low")
        if self.close_date < self.open_date:
            raise ValueError("close_date must be on or after open_date")
        if self.listing_date is not None and self.listing_date < self.close_date:
            raise ValueError("listing_date must be on or after close_date")
        return self


class PartialRecord(_Frozen):
    """The subset of IPO fields a single source contributes (Deep Dive #1, Module 3).

    Each ``DataSource.parse`` returns one of these; the hygiene/merge layer (Phase 1)
    reconciles partials from several sources into a canonical ``IPORecord``. All
    payload fields are optional because no single source provides everything; the
    ``source`` and ``fields`` keep provenance explicit.
    """

    source: str
    ipo_id: str
    fields: dict[str, object] = Field(default_factory=dict)


class ListingLabel(_Frozen):
    """The supervised label: gross listing-day return vs the issue price.

    Net-of-cost is computed downstream (Deep Dive #4) — ingestion stays cost-free.
    """

    ipo_id: str
    issue_price: float = Field(gt=0)
    listing_open: float = Field(gt=0)
    listing_close: float = Field(gt=0)
    listing_return_open: float
    listing_return_close: float


class IPOFeatures(_Frozen):
    """The point-in-time feature vector the model scores (Layer 2 output contract).

    Every field is a pure function of data known at or before ``asof`` (the
    subscription close). ``None`` marks a feature that could not be computed from
    as-of data; a missing *critical* feature drives ``INSUFFICIENT_SIGNAL``
    downstream (Inviolable Rule 3) rather than a fabricated value.
    """

    ipo_id: str
    asof: datetime  # decision-time clock; nothing after this may inform a feature

    # GMP — sentiment/direction proxy only (Inviolable Rule 5).
    gmp_level: float | None = None  # premium normalized by price-band top
    gmp_slope: float | None = None  # final-days trend

    # Subscription multiples.
    qib_sub: float | None = Field(default=None, ge=0)
    nii_sub: float | None = Field(default=None, ge=0)
    retail_sub: float | None = Field(default=None, ge=0)

    # Engineered features.
    anchor_quality: float | None = Field(default=None, ge=0, le=1)
    relative_valuation: float | None = Field(default=None, gt=0)  # issue_pe / peer_median
    ofs_fraction: float | None = Field(default=None, ge=0, le=1)
    market_regime: float | None = Field(default=None, ge=-1, le=1)

    # True once the subscription book has closed as of `asof`.
    book_closed: bool = False

    # Construction flags surfaced to the reason generator (e.g. "no_listed_peer",
    # "book_not_closed"). Never silent: a flagged condition is explained, not hidden.
    flags: tuple[str, ...] = ()


class Verdict(_Frozen):
    """The engine's complete output for one IPO (Layer 3 output contract).

    ``probability`` is the calibrated P(positive listing) and is ``None`` whenever
    the verdict is ``INSUFFICIENT_SIGNAL`` or the calibrator has not passed the
    reliability gate — an uncalibrated number is never shown (Inviolable Rule 1).
    Every claim in ``reason`` traces to a feature value.
    """

    ipo_id: str
    verdict: VerdictType
    probability: float | None = Field(default=None, ge=0, le=1)
    reason: str = ""
    watch: list[str] = Field(default_factory=list)
    kill_flags: list[str] = Field(default_factory=list)
