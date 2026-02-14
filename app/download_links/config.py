"""Configuration helpers for external HFS download links."""

from __future__ import annotations

import os
from pathlib import Path

from app.config import load_env_file

_HFS_BASE_URL_KEY = "HFS_BASE_URL"
_DOWNLOAD_LINK_SECRET_KEY = "DOWNLOAD_LINK_SECRET"
_DOWNLOAD_LINK_TTL_SECONDS_KEY = "DOWNLOAD_LINK_TTL_SECONDS"
_DOWNLOADS_ROOT_KEY = "DOWNLOADS_ROOT"


def get_hfs_base_url() -> str | None:
    """Resolve optional public HTTPS base URL used to serve user folders via HFS."""
    load_env_file()
    raw_url = os.getenv(_HFS_BASE_URL_KEY)
    if not raw_url:
        return None
    return raw_url.rstrip("/")


def get_download_link_secret() -> str:
    """Resolve secret used to sign expiring folder links."""
    load_env_file()
    secret = os.getenv(_DOWNLOAD_LINK_SECRET_KEY)
    if not secret:
        raise ValueError(f"Missing required environment variable: {_DOWNLOAD_LINK_SECRET_KEY}")
    return secret


def get_download_link_ttl_seconds() -> int:
    """Resolve link TTL in seconds, defaulting to 30 minutes."""
    load_env_file()
    raw_ttl = os.getenv(_DOWNLOAD_LINK_TTL_SECONDS_KEY, "1800")
    try:
        ttl_seconds = int(raw_ttl)
    except ValueError as exc:
        raise ValueError(
            f"Invalid integer in {_DOWNLOAD_LINK_TTL_SECONDS_KEY}: {raw_ttl}"
        ) from exc

    if ttl_seconds <= 0:
        raise ValueError(f"{_DOWNLOAD_LINK_TTL_SECONDS_KEY} must be greater than 0")
    return ttl_seconds


def get_downloads_root() -> Path:
    """Resolve local downloads root path used for per-user storage."""
    load_env_file()
    root = os.getenv(_DOWNLOADS_ROOT_KEY, "downloads")
    return Path(root)
