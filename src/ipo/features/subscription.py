"""Subscription features — institutional/retail confidence (Deep Dive #2).

Each is an oversubscription multiple captured at the subscription close. They are
point-in-time gated: before the book closes the closing figures do not exist yet, so
the features are ``None`` (which drives ``INSUFFICIENT_SIGNAL`` for the critical QIB
leg downstream), never a guessed value.
"""

from __future__ import annotations

from ipo.core.types import IPORecord


def subscription_features(
    record: IPORecord, *, book_closed: bool
) -> tuple[float | None, float | None, float | None]:
    """Return (qib, nii, retail) closing multiples, or all ``None`` if the book is open.

    QIB is the institutional valuation verdict (highest weight); retail the weakest
    (it partly echoes GMP). Normalization/weighting is applied later by the scorer.
    """
    if not book_closed:
        return None, None, None
    return record.qib_sub, record.nii_sub, record.retail_sub
