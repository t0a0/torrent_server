"""Configuration loading from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(ValueError):
    """Raised when required environment variables are missing or malformed."""


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_allowed_user_ids: frozenset[int]
    qbittorrent_base_url: str
    qbittorrent_username: str
    qbittorrent_password: str
    qbittorrent_verify_certificate: bool
    sqlite_path: str
    download_base_url: str
    download_token_secret: str
    download_token_ttl_seconds: int


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _parse_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"Invalid boolean value for {name}: {value}")


def _parse_allowed_ids(raw_ids: str) -> frozenset[int]:
    parsed_ids: set[int] = set()
    for item in raw_ids.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            parsed_ids.add(int(value))
        except ValueError as exc:
            raise ConfigError("TELEGRAM_ALLOWED_USER_IDS must contain integer IDs") from exc
    if not parsed_ids:
        raise ConfigError("At least one TELEGRAM_ALLOWED_USER_IDS entry is required")
    return frozenset(parsed_ids)


def load_settings() -> Settings:
    """Load and validate runtime settings from environment variables."""
    token_ttl = int(os.getenv("DOWNLOAD_TOKEN_TTL_SECONDS", "3600"))
    if token_ttl <= 0:
        raise ConfigError("DOWNLOAD_TOKEN_TTL_SECONDS must be greater than zero")

    return Settings(
        telegram_bot_token=_require_env("TELEGRAM_BOT_TOKEN"),
        telegram_allowed_user_ids=_parse_allowed_ids(_require_env("TELEGRAM_ALLOWED_USER_IDS")),
        qbittorrent_base_url=_require_env("QBITTORRENT_BASE_URL"),
        qbittorrent_username=_require_env("QBITTORRENT_USERNAME"),
        qbittorrent_password=_require_env("QBITTORRENT_PASSWORD"),
        qbittorrent_verify_certificate=_parse_bool("QBITTORRENT_VERIFY_CERTIFICATE", default=False),
        sqlite_path=os.getenv("SQLITE_PATH", "./data/torrent_server.db"),
        download_base_url=_require_env("DOWNLOAD_BASE_URL"),
        download_token_secret=_require_env("DOWNLOAD_TOKEN_SECRET"),
        download_token_ttl_seconds=token_ttl,
    )
