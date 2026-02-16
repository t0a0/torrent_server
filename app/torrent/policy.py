"""Policy and limit configuration for torrent input validation."""

from __future__ import annotations

import os
from pathlib import Path

from app.config import load_env_file

_MAX_TORRENT_BYTES_HARD_KEY = "MAX_TORRENT_BYTES_HARD"
_MAX_TORRENT_BYTES_WARN_KEY = "MAX_TORRENT_BYTES_WARN"
_MAX_MAGNET_URL_LENGTH_KEY = "MAX_MAGNET_URL_LENGTH"
_MAX_MAGNET_TRACKERS_KEY = "MAX_MAGNET_TRACKERS"
_MAX_TORRENT_FILE_COUNT_KEY = "MAX_TORRENT_FILE_COUNT"
_MAX_TORRENT_NAME_LENGTH_KEY = "MAX_TORRENT_NAME_LENGTH"
_MAX_TORRENT_TRACKER_URL_LENGTH_KEY = "MAX_TORRENT_TRACKER_URL_LENGTH"
_MAX_TORRENT_PATH_SEGMENT_LENGTH_KEY = "MAX_TORRENT_PATH_SEGMENT_LENGTH"
_MAX_TORRENT_AGGREGATE_BYTES_KEY = "MAX_TORRENT_AGGREGATE_BYTES"
_ADD_RATE_LIMIT_PER_MIN_KEY = "ADD_RATE_LIMIT_PER_MIN"
_TORRENT_INPUT_TMP_DIR_KEY = "TORRENT_INPUT_TMP_DIR"


def _get_int(key: str, default: int) -> int:
    load_env_file()
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid integer in {key}: {raw}") from exc


def get_max_torrent_bytes_hard() -> int:
    return _get_int(_MAX_TORRENT_BYTES_HARD_KEY, 2 * 1024 * 1024)


def get_max_torrent_bytes_warn() -> int:
    return _get_int(_MAX_TORRENT_BYTES_WARN_KEY, 512 * 1024)


def get_max_magnet_url_length() -> int:
    return _get_int(_MAX_MAGNET_URL_LENGTH_KEY, 8192)


def get_max_magnet_trackers() -> int:
    return _get_int(_MAX_MAGNET_TRACKERS_KEY, 100)


def get_max_torrent_file_count() -> int:
    return _get_int(_MAX_TORRENT_FILE_COUNT_KEY, 10_000)


def get_max_torrent_name_length() -> int:
    return _get_int(_MAX_TORRENT_NAME_LENGTH_KEY, 255)


def get_max_torrent_tracker_url_length() -> int:
    return _get_int(_MAX_TORRENT_TRACKER_URL_LENGTH_KEY, 2048)


def get_max_torrent_path_segment_length() -> int:
    return _get_int(_MAX_TORRENT_PATH_SEGMENT_LENGTH_KEY, 255)


def get_max_torrent_aggregate_bytes() -> int:
    return _get_int(_MAX_TORRENT_AGGREGATE_BYTES_KEY, 0)


def get_add_rate_limit_per_minute() -> int:
    return _get_int(_ADD_RATE_LIMIT_PER_MIN_KEY, 20)


def get_torrent_input_tmp_dir() -> Path:
    load_env_file()
    path = os.getenv(_TORRENT_INPUT_TMP_DIR_KEY, "tmp/torrent-inputs")
    return Path(path)
