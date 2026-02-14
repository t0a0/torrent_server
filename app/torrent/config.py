"""Configuration helpers for qBittorrent integration."""

from pathlib import Path
import os

from app.config import load_env_file

_QBIT_URL_KEY = "QBITTORRENT_URL"
_QBIT_USERNAME_KEY = "QBITTORRENT_USERNAME"
_QBIT_PASSWORD_KEY = "QBITTORRENT_PASSWORD"
_DOWNLOADS_ROOT_KEY = "DOWNLOADS_ROOT"



def get_qbittorrent_url() -> str:
    """Resolve qBittorrent Web UI URL from environment."""
    load_env_file()
    return os.getenv(_QBIT_URL_KEY, "http://127.0.0.1:8080")


def get_qbittorrent_username() -> str | None:
    """Resolve optional qBittorrent username from environment."""
    load_env_file()
    return os.getenv(_QBIT_USERNAME_KEY)


def get_qbittorrent_password() -> str | None:
    """Resolve optional qBittorrent password from environment."""
    load_env_file()
    return os.getenv(_QBIT_PASSWORD_KEY)


def get_downloads_root() -> Path:
    """Resolve local downloads root path used for per-user storage."""
    load_env_file()
    root = os.getenv(_DOWNLOADS_ROOT_KEY, "downloads")
    return Path(root)
