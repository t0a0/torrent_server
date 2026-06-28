"""Configuration helpers for qBittorrent integration."""

from pathlib import Path
import os

from app.config import load_env_file

_QBIT_URL_KEY = "QBITTORRENT_URL"
_QBIT_USERNAME_KEY = "QBITTORRENT_USERNAME"
_QBIT_PASSWORD_KEY = "QBITTORRENT_PASSWORD"
_ACTIVE_DOWNLOADS_ROOT_KEY = "ACTIVE_DOWNLOADS_ROOT"
_FINISHED_DOWNLOADS_ROOT_KEY = "FINISHED_DOWNLOADS_ROOT"
_DOWNLOADS_ROOT_KEY = "DOWNLOADS_ROOT"
_TORRENT_INPUT_TMP_DIR_KEY = "TORRENT_INPUT_TMP_DIR"
_DOWNLOAD_RECORDS_DB_PATH_KEY = "DOWNLOAD_RECORDS_DB_PATH"
_FINISHED_DOWNLOAD_RETENTION_DAYS_KEY = "FINISHED_DOWNLOAD_RETENTION_DAYS"

_MAX_TORRENT_BYTES_HARD = 2 * 1024 * 1024
_MAX_TORRENT_BYTES_WARN = 512 * 1024
_MAX_MAGNET_URL_LENGTH = 8192
_MAX_MAGNET_TRACKERS = 100
_MAX_TORRENT_FILE_COUNT = 10000
_MAX_TORRENT_NAME_LENGTH = 255
_MAX_TRACKER_URL_LENGTH = 2048
_MAX_PATH_SEGMENT_LENGTH = 255
_MAX_AGGREGATE_SIZE_BYTES = 0
_QUEUE_DOWNLOAD_RATE_LIMIT_PER_MIN = 10
_QBIT_API_TIMEOUT_SECONDS = 15
_QBIT_GLOBAL_UPLOAD_LIMIT_BYTES_PER_SEC = 1024 * 1024

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


def get_finished_downloads_root() -> Path:
    """Resolve local downloads root path used for per-user storage."""
    load_env_file()
    root = os.getenv(_FINISHED_DOWNLOADS_ROOT_KEY, "finished_downloads")
    return Path(root)


def get_active_downloads_root() -> Path:
    """Resolve local active-downloads root path used for qBittorrent save paths."""
    load_env_file()
    root = os.getenv(_ACTIVE_DOWNLOADS_ROOT_KEY, "active_downloads")
    return Path(root)


def get_downloads_root() -> Path:
    """Resolve the broader downloads root that qBittorrent saves into.

    Used to sweep up torrents queued directly via the qBittorrent Web UI (which
    save outside `active_downloads`) so the completion worker still moves and
    exposes them under the owner's finished-downloads folder.
    """
    load_env_file()
    root = os.getenv(_DOWNLOADS_ROOT_KEY, "/downloads")
    return Path(root)


def _get_int_env(key: str, default: int) -> int:
    load_env_file()
    raw_value = os.getenv(key)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"Invalid integer in {key}: {raw_value}") from exc


def get_max_torrent_bytes_hard() -> int:
    return _MAX_TORRENT_BYTES_HARD


def get_max_torrent_bytes_warn() -> int:
    return _MAX_TORRENT_BYTES_WARN


def get_max_magnet_url_length() -> int:
    return _MAX_MAGNET_URL_LENGTH


def get_max_magnet_trackers() -> int:
    return _MAX_MAGNET_TRACKERS


def get_max_torrent_file_count() -> int:
    return _MAX_TORRENT_FILE_COUNT


def get_max_torrent_name_length() -> int:
    return _MAX_TORRENT_NAME_LENGTH


def get_max_tracker_url_length() -> int:
    return _MAX_TRACKER_URL_LENGTH


def get_max_torrent_path_segment_length() -> int:
    return _MAX_PATH_SEGMENT_LENGTH


def get_max_torrent_aggregate_size_bytes() -> int:
    return _MAX_AGGREGATE_SIZE_BYTES


def get_queue_download_rate_limit_per_min() -> int:
    return _QUEUE_DOWNLOAD_RATE_LIMIT_PER_MIN


def get_torrent_input_tmp_dir() -> Path:
    load_env_file()
    raw_path = os.getenv(_TORRENT_INPUT_TMP_DIR_KEY, "tmp/torrent_inputs")
    return Path(raw_path)


def get_qbit_api_timeout_seconds() -> int:
    return _QBIT_API_TIMEOUT_SECONDS


def get_qbit_global_upload_limit_bytes_per_sec() -> int:
    return _QBIT_GLOBAL_UPLOAD_LIMIT_BYTES_PER_SEC


def get_download_records_db_path() -> Path:
    """Resolve SQLite path for finished download retention records."""
    load_env_file()
    raw_path = os.getenv(_DOWNLOAD_RECORDS_DB_PATH_KEY, "download_records.db")
    return Path(raw_path)


def get_finished_download_retention_days() -> int:
    """Resolve retention days for finished downloads cleanup."""
    return _get_int_env(_FINISHED_DOWNLOAD_RETENTION_DAYS_KEY, 7)
