"""Forward subscription series (v3-DP DP-1) — the banked intraday demand-book trajectory.

THE B1 WALL. This package is *structurally unreachable* from the scoring path, and that is the
whole point of it existing as its own top-level package rather than living under ``data/`` or
``core/``. The series it banks is the exact data a REJECTED model feature would want:

    B1 (subscription-trajectory-as-a-score-feature) was gated in v2 and returned a NULL RESULT.
    It is in the graveyard. Collecting the trajectory is NOT feeding it to the model, and
    possessing this data does NOT reopen that gate — reopening it is a separate, deliberate
    v2-protocol exercise (walk-forward, look-ahead shuffle, ECE/AUC across >=3 splits,
    PROMOTED-or-REJECTED with the graveyard updated either way). "We have the data now" is not
    "the gate is open."

``test_scoring_path_cannot_transitively_reach_service_or_archive`` asserts that importing
``ipo.features`` / ``ipo.model`` / ``ipo.calibration`` / ``ipo.core`` never lands ``ipo.series`` in
``sys.modules``. That test is the reason a future session cannot quietly cross this line: it does
not forbid a *chart* or an *offline study* from reading the series (DP-3 and DP-4 both do), only
the scorer.

One writer, one home: the series is written by exactly one VM-side writer (the DP-1 recorder,
piggybacking the ``ipo-ingest.service`` 30-min cycle) and never mixes with the current-state store.
"""

from ipo.series.models import CategoryReading, SubscriptionSample
from ipo.series.store import SeriesWriteError, SubscriptionSeriesStore

__all__ = [
    "CategoryReading",
    "SeriesWriteError",
    "SubscriptionSample",
    "SubscriptionSeriesStore",
]
