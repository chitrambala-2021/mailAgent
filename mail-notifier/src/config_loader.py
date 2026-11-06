"""Loads settings.yaml + .env and resolves project-relative paths."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "settings.yaml"


class ConfigError(Exception):
    """Raised when the configuration is missing or invalid."""


def resolve_path(path: str | Path) -> Path:
    """Return an absolute path; relative paths are taken from the project root."""
    p = Path(path).expanduser()
    return p if p.is_absolute() else PROJECT_ROOT / p


def load_settings(config_path: str | None = None) -> dict:
    load_dotenv(PROJECT_ROOT / ".env")

    path = resolve_path(config_path) if config_path else DEFAULT_CONFIG
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    _validate(data)
    return data


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) and value.strip() else default


def _validate(cfg: dict) -> None:
    accounts = cfg.get("accounts")
    if not isinstance(accounts, list) or not accounts:
        raise ConfigError("settings.yaml: 'accounts' must be a non-empty list")

    for i, acct in enumerate(accounts):
        if not isinstance(acct, dict) or "@" not in str(acct.get("email", "")):
            raise ConfigError(f"settings.yaml: accounts[{i}] needs a valid 'email'")
        provider = str(acct.get("provider", "auto")).lower()
        if provider not in ("auto", "gmail", "outlook"):
            raise ConfigError(
                f"settings.yaml: accounts[{i}].provider must be auto | gmail | outlook"
            )

    interval = cfg.get("poll_interval_minutes", 5)
    if not isinstance(interval, (int, float)) or interval < 1:
        raise ConfigError("settings.yaml: 'poll_interval_minutes' must be >= 1")

    mode = cfg.get("filters", {}).get("mode", "all")
    if mode not in ("all", "rules"):
        raise ConfigError("settings.yaml: filters.mode must be 'all' or 'rules'")
