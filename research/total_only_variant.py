"""Reduced-feature variant scorers for the Total-only comparison gate (research only).

OFF-MAIN / RESEARCH: this module is **not** wired into the shipped engine and lives in
``research/`` (excluded from the build), exactly like the prior gate probes. It exists to
answer one question: *if the only subscription signal legally available from a licensed
feed is the **total** oversubscription multiple (no QIB/NII/retail split), how close does a
model built on that single number come to the shipped full model?*

Two reduced arms are constructed, each reusing the **shipped** ``WeightedScorer`` code path
so the normalization is byte-identical to production (winsorize -> saturating map, same
config scales) — only the *inputs* change:

* ``qib_only``   — the scorer's QIB term alone (NII/retail dropped).
* ``total_only`` — the same subscription normalization applied to the **total** multiple,
  fed through the QIB slot so it gets the identical winsor/saturation transform.

Because the Phase-4 calibrator is a 2-parameter Platt sigmoid (``P = sigmoid(a*score+b)``),
the single feature's absolute weight is absorbed by ``a`` — so what each arm truly isolates
is the *ranking shape* of its input (rank by QIB, rank by total, or rank by the weighted
sum). That is precisely the question the operator posed.

Every arm shares the same eligible IPO set, listing dates and labels (taken from the shipped
full-model items); only ``ScoredItem.score`` differs. Nothing here mutates the shipped model.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from ipo.calibration.backtest import ScoredItem
from ipo.core.config import FeaturesConfig
from ipo.core.types import IPOFeatures, IPORecord
from ipo.model.scorer import WeightedScorer


def load_total_sub_by_id(csv_path: Path) -> dict[str, float]:
    """Read the total (overall) oversubscription multiple per IPO from the seed CSV.

    Mirrors ``benchmark.load_oos_rows`` — ``total_sub`` is a CSV column, not an
    ``IPORecord`` field. Rows without it are simply absent from the map.
    """
    totals: dict[str, float] = {}
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("total_sub"):
                totals[row["ipo_id"]] = float(row["total_sub"])
    return totals


def _score_single_multiple(scorer: WeightedScorer, multiple: float) -> float:
    """Score one subscription multiple through the shipped scorer's QIB path.

    Builds an ``IPOFeatures`` with only ``qib_sub`` populated (every other feature
    ``None`` -> dropped as neutral) so the returned scalar is exactly
    ``weight(qib) * saturate(winsorize(multiple, 0, winsor_max_x), saturation_scale_x)`` —
    the production normalization, no reimplementation.
    """
    feats = IPOFeatures(
        ipo_id="_variant_",
        asof=datetime(2020, 1, 1),
        qib_sub=multiple,
        book_closed=True,
    )
    return scorer.score(feats)


def qib_only_score(scorer: WeightedScorer, record: IPORecord) -> float | None:
    """The scorer's QIB contribution as the sole input (``None`` if QIB missing)."""
    if record.qib_sub is None:
        return None
    return _score_single_multiple(scorer, record.qib_sub)


def total_only_score(
    scorer: WeightedScorer, record: IPORecord, totals: dict[str, float]
) -> float | None:
    """The total multiple scored with the same subscription normalization (or ``None``)."""
    total = totals.get(record.ipo_id)
    if total is None:
        return None
    return _score_single_multiple(scorer, total)


def build_variant_items(
    full_items: list[ScoredItem],
    records: list[IPORecord],
    *,
    scorer: WeightedScorer,
    features_config: FeaturesConfig,  # noqa: ARG001 (kept for call-site symmetry / clarity)
    totals: dict[str, float],
) -> tuple[list[ScoredItem], list[ScoredItem]]:
    """Return (qib_only_items, total_only_items) aligned 1:1 with ``full_items``.

    The eligible set, dates and labels come straight from the shipped full-model items,
    so the three arms differ only in ``score``. An arm drops any IPO whose reduced input
    is missing — but on the 358 sample QIB and total are present for all (asserted by the
    caller), so all three arms are identical in membership.
    """
    rec_by_id = {r.ipo_id: r for r in records}
    qib_items: list[ScoredItem] = []
    total_items: list[ScoredItem] = []
    for it in full_items:
        rec = rec_by_id[it.ipo_id]
        q = qib_only_score(scorer, rec)
        t = total_only_score(scorer, rec, totals)
        if q is not None:
            qib_items.append(ScoredItem(it.ipo_id, it.listing_date, q, it.label))
        if t is not None:
            total_items.append(ScoredItem(it.ipo_id, it.listing_date, t, it.label))
    return qib_items, total_items
