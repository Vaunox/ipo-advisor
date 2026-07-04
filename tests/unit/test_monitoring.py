"""Verdict-accuracy monitoring: snapshots, drift alerts, and the injected-drift gate."""

from __future__ import annotations

from ipo.service.monitoring import (
    AccuracySnapshot,
    evaluate_drift,
    snapshot,
)

_CUTOFF = 0.65


def _snap(
    *, precision: float | None, ci_high: float, ece: float, n: int = 100, n_apply: int = 40
) -> AccuracySnapshot:
    return AccuracySnapshot(
        n=n,
        n_apply=n_apply,
        apply_precision=precision,
        precision_ci_low=max(0.0, (precision or 0.0) - 0.1),
        precision_ci_high=ci_high,
        ece=ece,
        base_rate=0.7,
    )


def test_snapshot_precision_and_base_rate() -> None:
    probs = [0.9, 0.8, 0.7, 0.6, 0.3]
    labels = [1, 1, 0, 1, 0]  # applies (>=0.65): 0.9->1, 0.8->1, 0.7->0  => 2/3
    snap = snapshot(probs, labels, apply_cutoff=_CUTOFF)
    assert snap.n == 5
    assert snap.n_apply == 3
    assert snap.apply_precision is not None
    assert abs(snap.apply_precision - 2 / 3) < 1e-9
    assert 0.0 < snap.precision_ci_low < 2 / 3 < snap.precision_ci_high <= 1.0
    assert abs(snap.base_rate - 0.6) < 1e-9


def test_snapshot_no_applies_yields_none_precision() -> None:
    snap = snapshot([0.3, 0.5, 0.6], [1, 0, 1], apply_cutoff=_CUTOFF)
    assert snap.n_apply == 0
    assert snap.apply_precision is None


def test_no_drift_is_ok() -> None:
    baseline = _snap(precision=0.85, ci_high=0.95, ece=0.06)
    window = _snap(precision=0.83, ci_high=0.92, ece=0.07)
    result = evaluate_drift(baseline, window)
    assert result.ok
    assert result.alerts == ()


def test_precision_departure_alerts() -> None:
    baseline = _snap(precision=0.85, ci_high=0.95, ece=0.06)
    # Even the optimistic end of the window CI (0.55) is below the baseline (0.85).
    window = _snap(precision=0.40, ci_high=0.55, ece=0.06)
    result = evaluate_drift(baseline, window)
    assert not result.ok
    assert [a.metric for a in result.alerts] == ["apply_precision"]


def test_precision_noise_does_not_alert() -> None:
    # Window precision dipped but its CI still reaches above the baseline -> noise, no alert.
    baseline = _snap(precision=0.85, ci_high=0.95, ece=0.06)
    window = _snap(precision=0.78, ci_high=0.90, ece=0.06)
    assert evaluate_drift(baseline, window).ok


def test_ece_blowout_alerts() -> None:
    baseline = _snap(precision=0.85, ci_high=0.95, ece=0.06)
    window = _snap(precision=0.85, ci_high=0.95, ece=0.20)
    result = evaluate_drift(baseline, window, ece_tolerance=0.03)
    assert [a.metric for a in result.alerts] == ["ece"]


def test_insufficient_sample_is_not_judged() -> None:
    baseline = _snap(precision=0.85, ci_high=0.95, ece=0.06)
    window = _snap(precision=0.0, ci_high=0.2, ece=0.5, n=5, n_apply=3)
    result = evaluate_drift(baseline, window, min_window=20)
    assert result.insufficient_sample
    assert result.ok  # cannot conclude drift on a thin window
    assert result.alerts == ()


def test_injected_drift_fires_alert() -> None:
    # GATE A4: a clean window matches the baseline; injecting drift trips the alert.
    clean_probs = [0.8] * 30 + [0.3] * 20
    clean_labels = [1] * 30 + [0] * 20
    baseline = snapshot(clean_probs, clean_labels, apply_cutoff=_CUTOFF)
    assert evaluate_drift(baseline, snapshot(clean_probs, clean_labels, apply_cutoff=_CUTOFF)).ok

    # Inject drift: the same APPLY-side IPOs now list as losers.
    drift_labels = [0] * 30 + [0] * 20
    drifted = snapshot(clean_probs, drift_labels, apply_cutoff=_CUTOFF)
    result = evaluate_drift(baseline, drifted)
    assert not result.ok
    assert any(a.metric == "apply_precision" for a in result.alerts)
