"""The supervised label builder (Deep Dive #1, Module 2).

The label is the gross listing-day return versus the issue price (band top, the
retail cut-off):

    listing_return_open  = (listing_open  - issue_price) / issue_price
    listing_return_close = (listing_close - issue_price) / issue_price

Ingestion stays cost-free and pure: the *net-of-cost* label the model predicts is
derived later (Deep Dive #4) from this gross return. Issues without listing data
(withdrawn, deferred, not-yet-listed) yield no label and are excluded from training
rather than fabricated.
"""

from __future__ import annotations

from ipo.core.logging import get_logger
from ipo.core.types import IPORecord, ListingLabel

_log = get_logger("ipo.data.labels")


def build_label(record: IPORecord) -> ListingLabel | None:
    """Return the gross listing-day label for ``record``, or ``None`` if not listable.

    ``None`` covers withdrawn/deferred issues and any IPO whose listing data has not
    arrived yet — the label is filled when listing data appears, never before.
    A single-exchange listing is fine: whichever exchange's prices were captured are
    used; the label is not nulled for that reason.
    """
    if record.listing_open is None or record.listing_close is None:
        _log.info(
            "label_skipped_no_listing",
            extra={"ipo_id": record.ipo_id, "listing_date": str(record.listing_date)},
        )
        return None

    issue_price = record.issue_price
    return ListingLabel(
        ipo_id=record.ipo_id,
        issue_price=issue_price,
        listing_open=record.listing_open,
        listing_close=record.listing_close,
        listing_return_open=(record.listing_open - issue_price) / issue_price,
        listing_return_close=(record.listing_close - issue_price) / issue_price,
    )


def build_labels(records: list[IPORecord]) -> list[ListingLabel]:
    """Build labels for every listable record, skipping (and logging) the rest."""
    labels: list[ListingLabel] = []
    for record in records:
        label = build_label(record)
        if label is not None:
            labels.append(label)
    return labels
