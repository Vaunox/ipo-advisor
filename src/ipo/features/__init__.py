"""Layer 2 — point-in-time feature construction.

``build_features`` is the public entry point; it is pure and identical in backtest
and live. ``leakage`` provides the firewall utilities the CI suite asserts against.
"""

from ipo.features.build import build_features
from ipo.features.gmp import GmpQuote
from ipo.features.leakage import future_mutated_record, is_point_in_time_safe

__all__ = [
    "build_features",
    "GmpQuote",
    "future_mutated_record",
    "is_point_in_time_safe",
]
