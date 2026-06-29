"""The supervised target the model actually predicts: net-of-cost positive listing.

Deep Dive #4, Module A. The strategy is a listing-day flip, so the honest exit is the
listing-day **open**. The operator keeps *net* of the listing-day sell cost, so the
label is net, not gross — a +0.3% "gain" the costs eat is correctly a loss.

Sell cost (NSE delivery/CNC, rates in config): STT 0.1% on the sell, the flat
Rs 15.34/ISIN DP charge, exchange + 18% GST on it, SEBI turnover fee. The flat DP
charge is amortized over a nominal retail application so it enters the per-unit
return. Buy side is the IPO allotment at the issue price (no brokerage/STT).
"""

from __future__ import annotations

from ipo.core.config import SellCosts


def net_listing_return(
    issue_price: float,
    exit_price: float,
    costs: SellCosts,
    *,
    nominal_application_value: float,
) -> float:
    """Return the net-of-cost listing-day return (fraction) for a flip at ``exit_price``.

    Args:
        issue_price: the price-band top (retail cut-off; the buy price).
        exit_price: the listing-day exit (open, by default).
        costs: configured sell-cost rates.
        nominal_application_value: rupee size used to amortize the flat DP charge.
    """
    qty = max(1.0, round(nominal_application_value / issue_price))
    buy_value = issue_price * qty
    sell_value = exit_price * qty

    exchange = costs.exchange_rate * sell_value
    turnover = (costs.stt_rate + costs.sebi_rate + costs.stamp_rate_sell) * sell_value
    gst = costs.gst_rate * (costs.brokerage + exchange)
    total_cost = turnover + exchange + gst + costs.brokerage + costs.dp_charge_per_isin

    net_proceeds = sell_value - total_cost
    return (net_proceeds - buy_value) / buy_value


def is_positive(net_return: float) -> int:
    """1 if the net-of-cost return is positive, else 0 (the binary calibration label)."""
    return 1 if net_return > 0.0 else 0
