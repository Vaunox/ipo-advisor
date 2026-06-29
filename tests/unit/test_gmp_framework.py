"""GMP framework: multi-source reconciliation, manipulation detection, and the gate.

The gate test is the point: an *informative* GMP signal is kept; a *pure-noise* GMP
is rejected (it degrades discrimination even if it looks 'calibrated'). This is what
makes GMP earn its weight (Deep Dive #5, Module D).
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from ipo.calibration.backtest import ScoredItem
from ipo.calibration.gmp_gate import gmp_recalibration_gate
from ipo.core.config import GmpConfig
from ipo.data.sources.gmp import (
    CsvGmpHistory,
    GMPPoint,
    detect_spike_collapse,
    from_aggregator_rows,
    has_sufficient_coverage,
    reconcile,
    to_quotes,
)

_CFG = GmpConfig(
    winsor_min=-100.0,
    winsor_max=1000.0,
    divergence_band_frac=0.5,
    collapse_drop_frac=0.4,
    min_coverage_days=3,
)


# --- reconciliation --------------------------------------------------------


def test_reconcile_uses_median_across_sources() -> None:
    d = date(2024, 1, 3)
    points = [
        GMPPoint(d, 100.0, "ipowatch"),
        GMPPoint(d, 110.0, "investorgain"),
        GMPPoint(d, 105.0, "chittorgarh"),
    ]
    series = reconcile(points, _CFG)
    assert len(series) == 1
    assert series[0].value == 105.0  # median, robust to spread
    assert series[0].n_sources == 3
    assert series[0].low_confidence is False


def test_reconcile_flags_large_divergence_low_confidence() -> None:
    d = date(2024, 1, 3)
    points = [GMPPoint(d, 50.0, "a"), GMPPoint(d, 200.0, "b")]  # huge disagreement
    series = reconcile(points, _CFG)
    assert series[0].low_confidence is True


def test_reconcile_winsorizes_absurd_prints() -> None:
    d = date(2024, 1, 3)
    points = [GMPPoint(d, 100.0, "a"), GMPPoint(d, 99999.0, "b")]  # absurd print
    series = reconcile(points, _CFG)
    # The 99999 is clipped to winsor_max=1000 before the median.
    assert series[0].value == 550.0  # median(100, 1000)


# --- manipulation / coverage ------------------------------------------------


def test_detect_spike_collapse() -> None:
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(4)]
    pts = reconcile(
        [GMPPoint(d, v, "a") for d, v in zip(days, [100, 200, 150, 80], strict=True)], _CFG
    )
    assert detect_spike_collapse(pts, _CFG) is True  # peak 200 -> 80 = -60%
    steady = reconcile(
        [GMPPoint(d, v, "a") for d, v in zip(days, [100, 105, 110, 108], strict=True)], _CFG
    )
    assert detect_spike_collapse(steady, _CFG) is False


def test_coverage_floor() -> None:
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(4)]
    series = reconcile([GMPPoint(d, 100.0, "a") for d in days], _CFG)
    assert has_sufficient_coverage(series, date(2024, 1, 4), _CFG) is True
    assert has_sufficient_coverage(series, date(2024, 1, 2), _CFG) is False  # only 2 days <= asof


def test_to_quotes_bridges_to_feature_layer() -> None:
    series = reconcile([GMPPoint(date(2024, 1, 3), 120.0, "a")], _CFG)
    quotes = to_quotes(series)
    assert quotes[0].on == date(2024, 1, 3)
    assert quotes[0].premium == 120.0


# --- aggregator + CSV sources ----------------------------------------------


def test_from_aggregator_rows_ipoalerts_shape() -> None:
    rows: list[dict[str, object]] = [
        {
            "date": "2024-01-03T20:00:00Z",
            "sources": [
                {"name": "ipowatch", "gmpPrice": 145},
                {"name": "investorgain", "gmpPrice": 120},
            ],
        }
    ]
    points = from_aggregator_rows("x", rows)
    assert len(points) == 2
    assert {p.value for p in points} == {145.0, 120.0}


def test_csv_gmp_history(tmp_path: object) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    csv_path = tmp_path / "gmp.csv"
    csv_path.write_text(
        "ipo_id,date,value,source\nacme,2024-01-03,120,ipowatch\nacme,2024-01-04,130,ipowatch\n",
        encoding="utf-8",
    )
    hist = CsvGmpHistory(csv_path)
    series = hist.series("acme")
    assert len(series) == 2
    assert hist.series("missing") == []


# --- the GMP re-calibration gate (Module D) --------------------------------


def _items(scores: np.ndarray, labels: np.ndarray) -> list[ScoredItem]:
    start = date(2021, 1, 1)
    return [
        ScoredItem(f"ipo{i}", start + timedelta(days=i * 2), float(scores[i]), int(labels[i]))
        for i in range(len(scores))
    ]


def test_gate_keeps_informative_gmp() -> None:
    rng = np.random.default_rng(7)
    n = 300
    latent = rng.normal(0, 1, n)
    labels = (rng.random(n) < 1.0 / (1.0 + np.exp(-2.0 * latent))).astype(int)
    without = _items(latent + rng.normal(0, 2.0, n), labels)  # noisy official view
    with_gmp = _items(latent + rng.normal(0, 0.3, n), labels)  # GMP sharpens the signal
    result = gmp_recalibration_gate(without, with_gmp, method="platt", initial=80, step=20)
    assert result.keep_gmp is True
    assert result.with_gmp.auc > result.without_gmp.auc


def test_gate_rejects_noise_gmp() -> None:
    rng = np.random.default_rng(8)
    n = 300
    latent = rng.normal(0, 1, n)
    labels = (rng.random(n) < 1.0 / (1.0 + np.exp(-2.0 * latent))).astype(int)
    without = _items(latent, labels)  # clean official signal
    with_noise = _items(rng.normal(0, 1, n), labels)  # GMP that is pure noise
    result = gmp_recalibration_gate(without, with_noise, method="platt", initial=80, step=20)
    assert result.keep_gmp is False  # noise collapses discrimination -> removed
