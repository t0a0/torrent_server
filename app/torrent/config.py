"""Configuration helpers for qBittorrent integration."""

from pathlib import Path
import os

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_QBIT_URL_KEY = "QBITTORRENT_URL"
_QBIT_USERNAME_KEY = "QBITTORRENT_USERNAME"
_QBIT_PASSWORD_KEY = "QBITTORRENT_PASSWORD"
_DOWNLOADS_ROOT_KEY = "DOWNLOADS_ROOT"


def load_env_file(env_path: Path = _ENV_FILE) -> None:
    """Load simple KEY=VALUE pairs from dotenv file into process env."""
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


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
