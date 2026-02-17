"""Configuration helpers for qBittorrent integration."""

from pathlib import Path
import os

from app.config import load_env_file

_QBIT_URL_KEY = "QBITTORRENT_URL"
_QBIT_USERNAME_KEY = "QBITTORRENT_USERNAME"
_QBIT_PASSWORD_KEY = "QBITTORRENT_PASSWORD"
_DOWNLOADS_ROOT_KEY = "DOWNLOADS_ROOT"
_MAX_TORRENT_BYTES_HARD_KEY = "MAX_TORRENT_BYTES_HARD"
_MAX_TORRENT_BYTES_WARN_KEY = "MAX_TORRENT_BYTES_WARN"
_MAX_MAGNET_URL_LENGTH_KEY = "MAX_MAGNET_URL_LENGTH"
_MAX_MAGNET_TRACKERS_KEY = "MAX_MAGNET_TRACKERS"
_MAX_TORRENT_FILE_COUNT_KEY = "MAX_TORRENT_FILE_COUNT"
_MAX_TORRENT_NAME_LENGTH_KEY = "MAX_TORRENT_NAME_LENGTH"
_MAX_TRACKER_URL_LENGTH_KEY = "MAX_TRACKER_URL_LENGTH"
_MAX_PATH_SEGMENT_LENGTH_KEY = "MAX_TORRENT_PATH_SEGMENT_LENGTH"
_MAX_AGGREGATE_SIZE_BYTES_KEY = "MAX_TORRENT_AGGREGATE_SIZE_BYTES"
_QUEUE_DOWNLOAD_RATE_LIMIT_PER_MIN_KEY = "QUEUE_DOWNLOAD_RATE_LIMIT_PER_MIN"
_TORRENT_INPUT_TMP_DIR_KEY = "TORRENT_INPUT_TMP_DIR"
_QBIT_API_TIMEOUT_SECONDS_KEY = "QBIT_API_TIMEOUT_SECONDS"
_QBIT_GLOBAL_UPLOAD_LIMIT_BYTES_PER_SEC_KEY = "QBIT_GLOBAL_UPLOAD_LIMIT_BYTES_PER_SEC"
_ACTIVE_DOWNLOADS_ROOT_KEY = "ACTIVE_DOWNLOADS_ROOT"

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
    return _get_int_env(_MAX_TORRENT_BYTES_HARD_KEY, 2 * 1024 * 1024)


def get_max_torrent_bytes_warn() -> int:
    return _get_int_env(_MAX_TORRENT_BYTES_WARN_KEY, 512 * 1024)


def get_max_magnet_url_length() -> int:
    return _get_int_env(_MAX_MAGNET_URL_LENGTH_KEY, 8192)


def get_max_magnet_trackers() -> int:
    return _get_int_env(_MAX_MAGNET_TRACKERS_KEY, 100)


def get_max_torrent_file_count() -> int:
    return _get_int_env(_MAX_TORRENT_FILE_COUNT_KEY, 10000)


def get_max_torrent_name_length() -> int:
    return _get_int_env(_MAX_TORRENT_NAME_LENGTH_KEY, 255)


def get_max_tracker_url_length() -> int:
    return _get_int_env(_MAX_TRACKER_URL_LENGTH_KEY, 2048)


def get_max_torrent_path_segment_length() -> int:
    return _get_int_env(_MAX_PATH_SEGMENT_LENGTH_KEY, 255)


def get_max_torrent_aggregate_size_bytes() -> int:
    return _get_int_env(_MAX_AGGREGATE_SIZE_BYTES_KEY, 0)


def get_queue_download_rate_limit_per_min() -> int:
    return _get_int_env(_QUEUE_DOWNLOAD_RATE_LIMIT_PER_MIN_KEY, 10)


def get_torrent_input_tmp_dir() -> Path:
    load_env_file()
    raw_path = os.getenv(_TORRENT_INPUT_TMP_DIR_KEY, "tmp/torrent_inputs")
    return Path(raw_path)


def get_qbit_api_timeout_seconds() -> int:
    return _get_int_env(_QBIT_API_TIMEOUT_SECONDS_KEY, 15)


def get_qbit_global_upload_limit_bytes_per_sec() -> int:
    return _get_int_env(_QBIT_GLOBAL_UPLOAD_LIMIT_BYTES_PER_SEC_KEY, 1024 * 1024)


def get_active_downloads_root() -> Path:
    """Resolve local active downloads root path used while torrents are in progress."""
    load_env_file()
    root = os.getenv(_ACTIVE_DOWNLOADS_ROOT_KEY, "activedownloads")
    return Path(root)
