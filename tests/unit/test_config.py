"""GATE 0: config loads & merges by env (default <- env file <- env vars <- overrides)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ipo.core.config import AppConfig, load_config


def test_defaults_load_from_repo_config() -> None:
    cfg = load_config(env="dev", environ={})
    assert isinstance(cfg, AppConfig)
    assert cfg.env == "dev"
    # default.yaml values are present.
    assert cfg.verdict_thresholds.apply == 0.65
    assert cfg.calibration.min_training_samples >= 100
    # sources.yaml merged in.
    assert "nse" in cfg.sources
    assert cfg.sources["nse"].authoritative is True
    assert cfg.sources["chittorgarh"].authoritative is False


def test_env_overlay_changes_log_level() -> None:
    dev = load_config(env="dev", environ={})
    prod = load_config(env="prod", environ={})
    assert dev.logging.level == "DEBUG"  # config/env/dev.yaml
    assert prod.logging.level == "WARNING"  # config/env/prod.yaml
    assert prod.notify.enabled is True


def test_env_var_override_wins_over_files() -> None:
    cfg = load_config(env="dev", environ={"IPO_LOGGING__LEVEL": "ERROR"})
    assert cfg.logging.level == "ERROR"


def test_env_var_scalar_coercion() -> None:
    cfg = load_config(env="dev", environ={"IPO_NOTIFY__ENABLED": "true"})
    assert cfg.notify.enabled is True


def test_ipo_env_selects_environment() -> None:
    cfg = load_config(environ={"IPO_ENV": "prod"})
    assert cfg.env == "prod"
    assert cfg.logging.level == "WARNING"


def test_explicit_overrides_have_highest_precedence() -> None:
    cfg = load_config(
        env="prod",
        environ={"IPO_LOGGING__LEVEL": "ERROR"},
        overrides={"logging": {"level": "CRITICAL"}},
    )
    assert cfg.logging.level == "CRITICAL"


def test_invalid_value_fails_loudly() -> None:
    with pytest.raises(ValidationError):
        load_config(env="dev", environ={"IPO_VERDICT_THRESHOLDS__APPLY": "5"})


def test_unknown_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        load_config(env="dev", overrides={"not_a_real_section": 1})
