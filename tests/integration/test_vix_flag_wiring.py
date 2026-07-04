"""v2 B2: India VIX enriches the cold-market FLAG (weight 0) — probabilities stay byte-identical.

Blending VIX into ``market_regime`` changes *which* IPOs are flagged cold, but must leave the
calibrated out-of-sample probabilities **byte-for-byte identical** to the trend-only / regime-free
model, because the regime weight is 0. If any OOS probability differs, VIX is leaking into the score
— a calibration-rule violation — and this fails. Equality is asserted exactly, not within a
tolerance. A companion assertion proves the enrichment is non-vacuous: VIX actually moves the flag
for at least one IPO (else byte-equality would prove nothing).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import pytest

from ipo.calibration.backtest import walk_forward
from ipo.calibration.dataset import load_records_from_csv, scored_items_from_records
from ipo.calibration.regime import NiftyRegime, VixSeries
from ipo.core.config import RegimeFeatureConfig, load_config
from ipo.core.constants import IST
from ipo.core.types import IPORecord, ListingLabel
from ipo.features.regime import compute_regime
from ipo.model.calibrator_placeholder import PlaceholderCalibrator
from ipo.model.scorer import WeightedScorer
from ipo.service.engine import VerdictEngine

_ROOT = Path(__file__).resolve().parents[2]
_CSV = _ROOT / "data" / "backfill" / "mainboard_ipos.csv"
_NIFTY = _ROOT / "data" / "backfill" / "nifty.csv"
_VIX = _ROOT / "data" / "backfill" / "vix.csv"

pytestmark = pytest.mark.skipif(
    not (_CSV.is_file() and _NIFTY.is_file() and _VIX.is_file()),
    reason="backfill data not present",
)


def _blend(
    nifty: NiftyRegime, vix: VixSeries, rc: RegimeFeatureConfig
) -> Callable[[date], float | None]:
    """A market_regime_of callable: the trend read with VIX layered on (the engine's blend)."""

    def of(day: date) -> float | None:
        trend = nifty.market_regime_feature(day)
        if trend is None:
            return None
        vol_stress = vix.vol_stress_at(day)
        if vol_stress is None:
            return trend
        return compute_regime(  # add-only: floor stress at 0 (VIX only tightens the flag)
            trend, max(0.0, vol_stress), trend_weight=rc.trend_weight, vol_weight=rc.vol_weight
        )

    return of


def test_vix_blend_changes_the_flag_but_not_the_probability() -> None:
    config = load_config(env="dev", environ={})
    cal = config.calibration
    rc = config.features.regime
    records = load_records_from_csv(_CSV)
    scorer = WeightedScorer(config.feature_weights, config.features)
    nifty = NiftyRegime(_NIFTY)
    vix = VixSeries(_VIX, reference=rc.vix_reference, scale=rc.vix_scale)
    blend = _blend(nifty, vix, rc)

    # --- non-vacuous: VIX actually moves the regime AND flips the cold flag for >=1 IPO ---
    cold = config.verdict_thresholds.cold_regime_flag
    trend_vals = {r.ipo_id: nifty.market_regime_feature(r.close_date) for r in records}
    blend_vals = {r.ipo_id: blend(r.close_date) for r in records}
    assert any(trend_vals[i] != blend_vals[i] for i in trend_vals)  # VIX exercised the blend
    flag_trend = {i for i, v in trend_vals.items() if v is not None and v <= cold}
    flag_blend = {i for i, v in blend_vals.items() if v is not None and v <= cold}
    assert flag_trend != flag_blend  # VIX changed the cold-market flag for at least one IPO

    # --- byte-equality: weight 0 -> identical raw scores -> identical OOS probabilities ---
    base = scored_items_from_records(
        records,
        scorer,
        features_config=config.features,
        sell_costs=config.sell_costs,
        nominal_application_value=cal.nominal_application_value,
    )
    withvix = scored_items_from_records(
        records,
        scorer,
        features_config=config.features,
        sell_costs=config.sell_costs,
        nominal_application_value=cal.nominal_application_value,
        market_regime_of=blend,
    )
    assert [it.score for it in base] == [it.score for it in withvix]

    rows_b = walk_forward(
        base, cal.method, initial=cal.walk_forward_initial, step=cal.walk_forward_step
    )
    rows_v = walk_forward(
        withvix, cal.method, initial=cal.walk_forward_initial, step=cal.walk_forward_step
    )
    assert [r.ipo_id for r in rows_b] == [r.ipo_id for r in rows_v]
    assert [r.prob for r in rows_b] == [r.prob for r in rows_v]


class _Repo:
    def __init__(self, records: list[IPORecord]) -> None:
        self._records = records

    def get(self, ipo_id: str) -> IPORecord | None:
        return next((r for r in self._records if r.ipo_id == ipo_id), None)

    def list_all(self) -> list[IPORecord]:
        return list(self._records)

    def upsert(self, record: IPORecord) -> None: ...

    def upsert_many(self, records: list[IPORecord]) -> None: ...

    def save_labels(self, labels: list[ListingLabel]) -> None: ...

    def load_labels(self) -> list[ListingLabel]:
        return []


def test_engine_uses_vix_when_supplied() -> None:
    """The composed engine (vix supplied) blends VIX into features.market_regime, not trend-only."""
    config = load_config(env="dev", environ={})
    rc = config.features.regime
    records = load_records_from_csv(_CSV)
    nifty = NiftyRegime(_NIFTY)
    vix = VixSeries(_VIX, reference=rc.vix_reference, scale=rc.vix_scale)

    # pick the record where VIX moves the regime the most (interior trend + non-neutral VIX), so
    # the blend genuinely differs — not a case where both are clamped to the same bound.
    def regime_shift(r: IPORecord) -> float:
        trend = nifty.market_regime_feature(r.close_date)
        vol_stress = vix.vol_stress_at(r.close_date)
        if trend is None or vol_stress is None:
            return -1.0
        blended = compute_regime(  # add-only, matching the engine
            trend, max(0.0, vol_stress), trend_weight=rc.trend_weight, vol_weight=rc.vol_weight
        )
        return abs(blended - trend)

    rec = max(records, key=regime_shift)
    assert regime_shift(rec) > 0.0  # VIX genuinely shifts this IPO's flag regime

    def engine(with_vix: bool) -> VerdictEngine:
        return VerdictEngine(
            repository=_Repo([rec]),
            calibrator=PlaceholderCalibrator(),
            scorer=WeightedScorer(config.feature_weights, config.features),
            config=config,
            regime=nifty,
            vix=vix if with_vix else None,
            clock=lambda: datetime(2026, 7, 4, tzinfo=IST),
        )

    trend_only = engine(False).features_for(rec).market_regime
    blended = engine(True).features_for(rec).market_regime
    assert trend_only is not None and blended is not None
    assert blended != trend_only  # the engine actually layered VIX onto the flag regime
