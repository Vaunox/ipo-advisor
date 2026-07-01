"""Live verdict engine — Phase 6, the Layer-5 composition.

Composes the persisted Repository + Calibrator + ScoringModel + NiftyRegime into live
verdicts. Two invariants it must preserve through the compose:

* **market_regime is FLAG-ONLY.** It is wired into the live feature build so the cold-market
  annotation can fire, but its scorer weight is 0 — so the probability the engine emits for an
  IPO equals what the official-only path emits, byte-for-byte. The live path is NOT a back-door
  for regime to touch the score (asserted in tests/integration/test_engine.py).
* **The probability stays gated.** If the calibrator has not passed the reliability gate, the
  engine emits the verdict with the uncalibrated banner and NO probability (Inviolable Rule 1)
  — inherited unchanged from ``evaluate``.

GMP is absent (``None``) by design until it earns its place (docs/GMP_GATE.md). The decision
clock is the subscription-close EOD once the book has closed (matching the backtest's as-of),
else "now" — an open book yields INSUFFICIENT_SIGNAL until it closes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ipo.calibration.regime import NiftyRegime
from ipo.core.calendar import now_ist
from ipo.core.config import AppConfig
from ipo.core.constants import IST
from ipo.core.interfaces import Calibrator, Repository, ScoringModel
from ipo.core.types import IPOFeatures, IPORecord, Verdict
from ipo.features.build import build_features
from ipo.model.verdict import evaluate
from ipo.service.views import IPODetail

_CLOSE_EOD_HOUR = 18  # decision clock = end of the subscription-close day (IST), as in backtest


class VerdictEngine:
    """Turns stored IPO records into live verdicts (regime flag-only, GMP absent)."""

    def __init__(
        self,
        *,
        repository: Repository,
        calibrator: Calibrator,
        scorer: ScoringModel,
        config: AppConfig,
        regime: NiftyRegime | None = None,
        clock: Callable[[], datetime] = now_ist,
    ) -> None:
        """Bind the composed dependencies; ``regime=None`` disables the cold-market flag."""
        self._repo = repository
        self._calibrator = calibrator
        self._scorer = scorer
        self._config = config
        self._regime = regime
        self._clock = clock

    def decision_asof(self, record: IPORecord) -> datetime:
        """Decision clock: the close EOD once the book has closed, else 'now' (open book)."""
        close_eod = datetime(
            record.close_date.year,
            record.close_date.month,
            record.close_date.day,
            _CLOSE_EOD_HOUR,
            tzinfo=IST,
        )
        now = self._clock()
        return close_eod if now >= close_eod else now

    def features_for(self, record: IPORecord, *, asof: datetime | None = None) -> IPOFeatures:
        """Build the point-in-time feature vector exactly as ``verdict_for`` scores it.

        The single feature-build path, so anything read off it (the detail view's feature values,
        the cold-market flag, the contribution breakdown) is the *same* input that produced the
        verdict — never a second computation that could disagree. ``market_regime`` is populated
        point-in-time as-of the decision clock (weight 0 → flag-only); GMP is ``None``.
        """
        when = asof if asof is not None else self.decision_asof(record)
        market_regime = (
            self._regime.market_regime_feature(when.date()) if self._regime is not None else None
        )
        return build_features(
            record, when, market_regime=market_regime, config=self._config.features
        )

    def verdict_for(self, record: IPORecord, *, asof: datetime | None = None) -> Verdict:
        """Compute the live verdict for one IPO.

        The probability is whatever ``evaluate`` blesses — i.e. ``None`` with the uncalibrated
        banner if the reliability gate hasn't passed (Inviolable Rule 1).
        """
        return evaluate(
            record,
            self.features_for(record, asof=asof),
            scorer=self._scorer,
            calibrator=self._calibrator,
            config=self._config,
        )

    def detail(self, record: IPORecord, *, asof: datetime | None = None) -> IPODetail:
        """Verdict + the features and signed contributions that produced it (read-only).

        Builds the feature vector once and reuses it for the verdict and the contribution
        breakdown, so the explanation the front end renders is exactly the arithmetic behind the
        shown verdict (Layer-3 transparency): no recomputation, no second scoring path.
        """
        features = self.features_for(record, asof=asof)
        verdict = evaluate(
            record,
            features,
            scorer=self._scorer,
            calibrator=self._calibrator,
            config=self._config,
        )
        return IPODetail(
            record=record,
            verdict=verdict,
            features=features,
            contributions=self._scorer.contributions(features),
        )

    def verdicts(self, *, asof: datetime | None = None) -> list[Verdict]:
        """Compute verdicts for every stored IPO."""
        return [self.verdict_for(record, asof=asof) for record in self._repo.list_all()]

    def get_record(self, ipo_id: str) -> IPORecord | None:
        """Look up a stored IPO record by id (read-through to the repository, for the API)."""
        return self._repo.get(ipo_id)

    def records(self) -> list[IPORecord]:
        """All stored IPO records (read-through, for the scheduler's cadence/iteration)."""
        return self._repo.list_all()
