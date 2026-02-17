"""Torrent services for qBittorrent integration."""

from .service import CompletedTorrent, FailedTorrent, TorrentService

__all__ = ["TorrentService", "CompletedTorrent", "FailedTorrent"]
