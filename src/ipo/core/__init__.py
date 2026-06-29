"""Core: types, Protocols, config/secrets loaders, logging, NSE calendar, constants.

This package has no dependency on any other layer — everything else depends on it.
"""

from ipo.core.config import AppConfig, load_config
from ipo.core.interfaces import (
    Calibrator,
    DataSource,
    Notifier,
    Repository,
    ScoringModel,
)
from ipo.core.types import (
    AnchorAllotment,
    IPOFeatures,
    IPORecord,
    ListingLabel,
    PartialRecord,
    RawResponse,
    Segment,
    Verdict,
    VerdictType,
)

__all__ = [
    "AppConfig",
    "load_config",
    "Calibrator",
    "DataSource",
    "Notifier",
    "Repository",
    "ScoringModel",
    "AnchorAllotment",
    "IPOFeatures",
    "IPORecord",
    "ListingLabel",
    "PartialRecord",
    "RawResponse",
    "Segment",
    "Verdict",
    "VerdictType",
]
