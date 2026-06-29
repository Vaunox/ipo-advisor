"""Layer 3 — scoring core: features -> verdict + grounded reason.

``evaluate`` is the public entry point (the Layer-3 output contract). The calibrator
is the marked ``PlaceholderCalibrator`` until Phase 4 replaces it past the gate.
"""

from ipo.model.calibrator_placeholder import PlaceholderCalibrator
from ipo.model.killflags import kill_flags
from ipo.model.reason import generate_reason
from ipo.model.scorer import WeightedScorer
from ipo.model.verdict import evaluate, map_probability, missing_critical

__all__ = [
    "PlaceholderCalibrator",
    "WeightedScorer",
    "kill_flags",
    "generate_reason",
    "evaluate",
    "map_probability",
    "missing_critical",
]
