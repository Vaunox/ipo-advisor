"""Retail allotment odds — a downstream, display-only **approximation** (v2 A3, P(allotment) only).

When the retail portion is **under-subscribed**, everyone is allotted in full. When it is
**oversubscribed**, allotment is a **whole-lot lottery decided by the number of applicants**, not a
pro-rata split of the subscription — so a minimum-lot application's chance of allotment is only
*approximately* the reciprocal of the retail subscription multiple. ``1 / retail_sub`` is a
**proxy**: it assumes every applicant bid exactly one lot, and it diverges from the real allotment
ratio to the extent applicants bid multiple lots (which tends to make actual odds *better* than the
proxy, since fewer applications compete for the same shares). It is therefore surfaced as an
**estimate**, labelled distinctly, and its real accuracy is measured against a fixture of actual
historical allotment ratios (`tests/fixtures/retail_allotment_ratios.json`, reported gap in
`docs/v2/A3_ALLOTMENT_ODDS.md`) — **not** tuned to match it.

Why it's worth showing: a strong IPO can still have near-zero allotment odds, and the user should
see that alongside the verdict. This is **display context only** — a downstream computation on the
already-ingested retail subscription, in a **separate code path** that never touches the scorer or
the calibrator (Track A: no gate, no calibration impact). The scoring path is unchanged not because
some Δprob is proven zero, but because these odds are computed entirely outside it.

Scope (operator decision, 2026-07-04): P(allotment) only — the expected-value formula
(gain-magnitude × odds − opportunity cost) is intentionally dropped, because the gain term needs a
magnitude the model deliberately doesn't produce and the ~3-day ASBA opportunity cost is negligible
(~₹8 on a typical application); neither earns its complexity.
"""

from __future__ import annotations


def retail_allotment_odds(retail_sub: float | None) -> float | None:
    """Approximate probability a minimum-lot retail application is allotted (from retail_sub).

    ``min(1, 1 / retail_sub)`` — full allotment (1.0) when retail is under-subscribed
    (``retail_sub <= 1``), else the reciprocal of the oversubscription. This is a **proxy** for a
    whole-lot lottery (see the module docstring), not an exact allotment ratio; callers must present
    it as an estimate. Returns ``None`` when the retail multiple is unknown or not yet meaningful
    (``None`` / non-positive — e.g. no retail bids on an open book), so the UI shows nothing rather
    than a fabricated certainty.
    """
    if retail_sub is None or retail_sub <= 0.0:
        return None
    return min(1.0, 1.0 / retail_sub)
