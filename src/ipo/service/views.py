"""API view models (DTOs) — read-only projections the API serializes.

These carry **no logic**: they package what the engine already computed so the front end can
render the detail view (the signed feature contributions behind the score, and the point-in-time
features behind the cold-market flag and the shown feature values) without any second scoring
path. Every field is verbatim engine output — the ``verdict`` here is byte-for-byte the one the
``/verdict`` endpoint returns for the same IPO (asserted in tests/integration/test_api.py).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from ipo.core.types import IPOFeatures, IPORecord, Verdict, VerdictType


class IPODetail(BaseModel):
    """One IPO's record + verdict + the features and signed contributions that produced it.

    ``contributions`` is the scorer's per-feature signed breakdown (Layer-3 transparency): each
    key is a named feature, each value its signed contribution to the raw score. It is the actual
    arithmetic behind ``verdict``, not a narrative — empty/partial when the engine abstained
    (a blind record is never scored). ``features`` are the same point-in-time inputs the verdict
    was scored on (regime flag-only, GMP absent).
    """

    record: IPORecord
    verdict: Verdict
    features: IPOFeatures
    contributions: dict[str, float]


class HistoryRow(BaseModel):
    """One past IPO: its point-in-time verdict paired with the actual net-of-cost outcome.

    ``verdict``/``probability`` are what the engine would have emitted at the decision clock
    (subscription-close EOD) from as-of features only — the listing label is never read into a
    feature (Inviolable Rule 2), so predicted and actual stay independent. ``net_return`` is the
    model's own target basis (net-of-cost listing-day return, the flip exit at the listing open),
    and ``listed_positive`` its binary label. This is the honest "predicted vs actual" the
    History view and the calibration scorecard are built from.
    """

    ipo_id: str
    name: str
    listing_date: date | None
    verdict: VerdictType
    probability: float | None
    net_return: float
    gross_return: float
    listed_positive: bool


class ReliabilityBinView(BaseModel):
    """One reliability-diagram bucket: mean predicted probability vs observed rate and count."""

    mean_predicted: float
    observed_rate: float
    count: int


class CalibrationView(BaseModel):
    """The calibration the History reliability diagram + scorecard render (read-only).

    The metrics and ``bins`` are the **held-out** walk-forward out-of-sample reliability (generated
    by scripts/run_reliability_export.py) — never an in-sample recompute, so the diagram shows the
    honest calibration (Inviolable Rule 1). ``version`` and ``gate_passed`` come live from the
    loaded calibrator. When no report has been generated, the metrics are ``None`` and ``bins`` is
    empty (``source`` says so) — the UI degrades gracefully rather than inventing a curve.
    """

    version: str
    gate_passed: bool
    source: str
    n: int
    base_rate: float | None
    ece: float | None
    brier: float | None
    auc: float | None
    bins: list[ReliabilityBinView]
