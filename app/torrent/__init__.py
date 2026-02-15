"""Torrent services for qBittorrent integration."""

from .service import TorrentService, TorrentServiceError
from .validators import (
    MagnetValidationResult,
    TorrentFileValidationResult,
    ValidationError,
    validate_magnet_url,
    validate_torrent_file,
)

__all__ = [
    "MagnetValidationResult",
    "TorrentFileValidationResult",
    "TorrentService",
    "TorrentServiceError",
    "ValidationError",
    "validate_magnet_url",
    "validate_torrent_file",
]
