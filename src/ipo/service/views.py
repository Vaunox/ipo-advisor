"""API view models (DTOs) — read-only projections the API serializes.

These carry **no logic**: they package what the engine already computed so the front end can
render the detail view (the signed feature contributions behind the score, and the point-in-time
features behind the cold-market flag and the shown feature values) without any second scoring
path. Every field is verbatim engine output — the ``verdict`` here is byte-for-byte the one the
``/verdict`` endpoint returns for the same IPO (asserted in tests/integration/test_api.py).
"""

from __future__ import annotations

from pydantic import BaseModel

from ipo.core.types import IPOFeatures, IPORecord, Verdict


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
