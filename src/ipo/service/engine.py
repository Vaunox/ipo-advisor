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
from ipo.core.types import IPORecord, Verdict
from ipo.features.build import build_features
from ipo.model.verdict import evaluate

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

    def verdict_for(self, record: IPORecord, *, asof: datetime | None = None) -> Verdict:
        """Compute the live verdict for one IPO.

        ``market_regime`` is populated point-in-time as-of the decision clock (weight 0 →
        flag-only); GMP is ``None`` (out of the model). The probability is whatever ``evaluate``
        blesses — i.e. ``None`` with the uncalibrated banner if the reliability gate hasn't passed.
        """
        when = asof if asof is not None else self.decision_asof(record)
        market_regime = (
            self._regime.market_regime_feature(when.date()) if self._regime is not None else None
        )
        features = build_features(
            record, when, market_regime=market_regime, config=self._config.features
        )
        return evaluate(
            record,
            features,
            scorer=self._scorer,
            calibrator=self._calibrator,
            config=self._config,
        )

    def verdicts(self, *, asof: datetime | None = None) -> list[Verdict]:
        """Compute verdicts for every stored IPO."""
        return [self.verdict_for(record, asof=asof) for record in self._repo.list_all()]

    def get_record(self, ipo_id: str) -> IPORecord | None:
        """Look up a stored IPO record by id (read-through to the repository, for the API)."""
        return self._repo.get(ipo_id)
