"""Layered configuration loader (Ground Rule 2).

Precedence, lowest to highest:

    config/default.yaml  +  config/sources.yaml
        <- config/env/<env>.yaml          (environment overlay)
        <- IPO_* environment variables     (deploy-time overrides)
        <- explicit ``overrides`` argument (tests / programmatic use)

The merged mapping is validated into a typed ``AppConfig`` so a malformed value
fails loudly at load time (Ground Rule 7). Secrets are NEVER read here — see
``core.secrets``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_ENV = "dev"
ENV_SELECT_VAR = "IPO_ENV"
ENV_OVERRIDE_PREFIX = "IPO_"
NESTED_DELIM = "__"

# Repo root is three parents up from this file: src/ipo/core/config.py -> repo.
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_DIR = _REPO_ROOT / "config"


# --- Typed schema -----------------------------------------------------------


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class LoggingConfig(_Section):
    """Structured-logging settings (see ``core.logging``)."""

    level: str = "INFO"
    # Aliased to the YAML key ``json``; the Python name avoids colliding with
    # pydantic's ``BaseModel.json`` method.
    json_output: bool = Field(default=True, alias="json")


class StorageConfig(_Section):
    """Local Parquet store and calibrator-artifact locations."""

    data_dir: str = "data_store"
    calibrator_dir: str = "data_store/calibrators"
    # Append-only, collect-forward day-wise subscription bank (v2 A1). Under the
    # gitignored data_store/ — banked observations are local data, never committed.
    daywise_dir: str = "data_store/daywise"


class ScrapeConfig(_Section):
    """Polite-scraper settings (Deep Dive #1, Module 3) and refresh cadence."""

    rate_limit_per_sec: float = 0.5
    backoff_factor: float = 2.0
    max_retries: int = 4
    user_agent: str = "ipo-advisor/0.1"
    cadence_minutes_default: int = 360
    cadence_minutes_subscription_window: int = 30
    # When true, the running service pulls live current mainboard IPOs from NSE each cycle
    # (the scheduler's refresh). Off → serve the seeded store only. See docs/SHIPPED_APP_GAPS.md
    # for the public-distribution caveat (per-user scraping of NSE's robots-disallowed /api).
    live_ingest: bool = True


class VerdictThresholds(_Section):
    """APPLY/MARGINAL probability cutoffs — earned and tuned in Phase 4."""

    apply: float = Field(default=0.65, ge=0, le=1)
    marginal: float = Field(default=0.50, ge=0, le=1)
    # Below this market_regime, flag the verdict "cold market — probability less certain"
    # (the regime stress-test landed on gate/flag, not forcing the cold probability).
    cold_regime_flag: float = Field(default=-0.3, ge=-1, le=1)


class CalibrationConfig(_Section):
    """Settings governing the SACRED Phase-4 reliability gate."""

    method: str = "platt"
    reliability_tolerance: float = Field(default=0.10, gt=0, le=1)
    n_buckets: int = Field(default=10, gt=1)
    min_training_samples: int = Field(default=100, ge=1)
    random_seed: int = 17
    exit_price: str = "open"
    nominal_application_value: float = Field(default=15000.0, gt=0)
    walk_forward_initial: int = Field(default=60, ge=10)
    walk_forward_step: int = Field(default=20, ge=1)
    min_auc: float = Field(default=0.55, ge=0.5, le=1)
    base_rate_margin: float = Field(default=0.05, ge=0, le=1)


class SellCosts(_Section):
    """NSE delivery (CNC) listing-day sell-cost rates (structural constants in core)."""

    brokerage: float = 0.0
    stt_rate: float = 0.001
    dp_charge_per_isin: float = 15.34
    exchange_rate: float = 0.0000297
    gst_rate: float = 0.18
    sebi_rate: float = 0.000001
    stamp_rate_sell: float = 0.0


class KillFlagConfig(_Section):
    """Hard-override thresholds (Deep Dive #3) — sanity bounds, not return-tuned."""

    gmp_collapse_slope_pct: float = -10.0
    near_total_ofs: float = Field(default=0.95, ge=0, le=1)


class GmpConfig(_Section):
    """Grey-market premium reconstruction settings (Deep Dive #5)."""

    winsor_min: float = -100.0
    winsor_max: float = 1000.0
    divergence_band_frac: float = Field(default=0.5, ge=0)
    collapse_drop_frac: float = Field(default=0.4, ge=0, le=1)
    min_coverage_days: int = Field(default=3, ge=1)
    sources: list[str] = Field(default_factory=list)
    primary: str = "investorgain"


class NotifyConfig(_Section):
    """Notifier channel and the verdict threshold that triggers a push."""

    enabled: bool = False
    channel: str = "none"
    threshold_verdict: str = "APPLY"


class SourceConfig(_Section):
    """Per-source URL and flags (``authoritative`` distinguishes official from aggregator)."""

    base_url: str
    authoritative: bool = False
    enabled: bool = True


class IngestConfig(_Section):
    """Ingestion settings: backfill window, seed path, raw cache, trust policy."""

    backfill_start_date: str = "2021-01-01"
    seed_csv: str = "seed/mainboard_ipos.csv"
    raw_cache_dir: str = "data_store/raw_cache"
    official_required_fields: list[str] = Field(default_factory=list)


class GmpFeatureConfig(_Section):
    """GMP normalization knobs (Deep Dive #2)."""

    winsor_max_pct: float = 100.0
    saturation_scale_pct: float = 25.0
    slope_days: int = 2
    slope_scale_pct: float = 15.0


class SubscriptionFeatureConfig(_Section):
    """Subscription-multiple normalization knobs."""

    winsor_max_x: float = 200.0
    saturation_scale_x: float = 20.0


class AnchorFeatureConfig(_Section):
    """Anchor-quality composite weights and the maintained recognized-anchor list."""

    recognized: list[str] = Field(default_factory=list)
    weight_marquee: float = 0.5
    weight_lockin: float = 0.3
    weight_full_placement: float = 0.2
    lockin_reference_days: int = 90


class ValuationFeatureConfig(_Section):
    """Relative-valuation policy, including the 'no listed peers' case."""

    peerless_policy: str = "neutral_flag"  # neutral_flag | mild_negative


class RegimeFeatureConfig(_Section):
    """Market-regime blend weights (trend vs volatility)."""

    trend_weight: float = 0.6
    vol_weight: float = 0.4


class FeaturesConfig(_Section):
    """Feature-construction configuration (Layer 2)."""

    gmp: GmpFeatureConfig = Field(default_factory=GmpFeatureConfig)
    subscription: SubscriptionFeatureConfig = Field(default_factory=SubscriptionFeatureConfig)
    anchor: AnchorFeatureConfig = Field(default_factory=AnchorFeatureConfig)
    valuation: ValuationFeatureConfig = Field(default_factory=ValuationFeatureConfig)
    regime: RegimeFeatureConfig = Field(default_factory=RegimeFeatureConfig)
    # Phase 4 official-only model: QIB is critical; Phase 5 re-adds "gmp_level".
    critical_features: list[str] = Field(default_factory=lambda: ["qib_sub"])


class AppConfig(BaseModel):
    """The fully-merged, validated configuration for one run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    env: str = DEFAULT_ENV
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    scrape: ScrapeConfig = Field(default_factory=ScrapeConfig)
    verdict_thresholds: VerdictThresholds = Field(default_factory=VerdictThresholds)
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)
    sell_costs: SellCosts = Field(default_factory=SellCosts)
    feature_weights: dict[str, float] = Field(default_factory=dict)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    killflags: KillFlagConfig = Field(default_factory=KillFlagConfig)
    gmp: GmpConfig = Field(default_factory=GmpConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)
    ingest: IngestConfig = Field(default_factory=IngestConfig)
    sources: dict[str, SourceConfig] = Field(default_factory=dict)


# --- Loading helpers --------------------------------------------------------


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a mapping at top level")
    return data


def _deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` onto ``base`` (overlay wins); returns a new dict."""
    merged: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _coerce_scalar(raw: str) -> Any:
    """Parse an env-var string as a YAML scalar so ``"0.7"`` -> float, ``"true"`` -> bool."""
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError:
        return raw


def _env_overrides(environ: Mapping[str, str]) -> dict[str, Any]:
    """Build a nested override dict from ``IPO_`` env vars (``__`` marks nesting).

    ``IPO_LOGGING__LEVEL=ERROR`` -> ``{"logging": {"level": "ERROR"}}``. The reserved
    ``IPO_ENV`` selector is not itself an override key.
    """
    result: dict[str, Any] = {}
    for key, value in environ.items():
        if not key.startswith(ENV_OVERRIDE_PREFIX) or key == ENV_SELECT_VAR:
            continue
        path = key[len(ENV_OVERRIDE_PREFIX) :].lower().split(NESTED_DELIM)
        cursor = result
        for part in path[:-1]:
            nxt = cursor.setdefault(part, {})
            if not isinstance(nxt, dict):
                raise ValueError(f"Env override {key} conflicts with a scalar at '{part}'")
            cursor = nxt
        cursor[path[-1]] = _coerce_scalar(value)
    return result


def load_config(
    env: str | None = None,
    *,
    config_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> AppConfig:
    """Load, merge by precedence, and validate the configuration.

    Args:
        env: Environment name (``dev``/``prod``/...). Falls back to ``IPO_ENV`` then
            ``DEFAULT_ENV``.
        config_dir: Directory holding the YAML files; defaults to ``<repo>/config``.
        environ: Environment mapping for overrides; defaults to ``os.environ``
            (injectable for deterministic tests).
        overrides: Highest-precedence explicit overrides (programmatic / tests).

    Returns:
        A validated, frozen ``AppConfig``.
    """
    environ = os.environ if environ is None else environ
    config_dir = DEFAULT_CONFIG_DIR if config_dir is None else config_dir
    resolved_env = env or environ.get(ENV_SELECT_VAR) or DEFAULT_ENV

    merged = _read_yaml(config_dir / "default.yaml")
    merged = _deep_merge(merged, _read_yaml(config_dir / "sources.yaml"))
    merged = _deep_merge(merged, _read_yaml(config_dir / "env" / f"{resolved_env}.yaml"))
    merged = _deep_merge(merged, _env_overrides(environ))
    if overrides:
        merged = _deep_merge(merged, overrides)

    merged["env"] = resolved_env
    return AppConfig.model_validate(merged)
