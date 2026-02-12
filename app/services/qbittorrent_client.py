"""Thin adapter around qbittorrent-api for easier future replacement."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from app.config import Settings


@dataclass(frozen=True)
class TorrentSummary:
    hash: str
    name: str
    state: str
    progress: float


def _create_api_client(settings: Settings) -> Any:
    qbittorrentapi = import_module("qbittorrentapi")
    return qbittorrentapi.Client(
        host=settings.qbittorrent_base_url,
        username=settings.qbittorrent_username,
        password=settings.qbittorrent_password,
        VERIFY_WEBUI_CERTIFICATE=settings.qbittorrent_verify_certificate,
    )


class QBittorrentClient:
    """Wrapper around qBittorrent Web API interactions used by the app."""

    def __init__(self, settings: Settings) -> None:
        self._client = _create_api_client(settings)

    def login(self) -> None:
        """Open an authenticated session against qBittorrent."""
        self._client.auth_log_in()

    def add_magnet(self, magnet_uri: str) -> None:
        """Add a magnet URI to qBittorrent."""
        self._client.torrents_add(urls=magnet_uri)

    def list_torrents(self) -> list[TorrentSummary]:
        """Return lightweight torrent status data for bot/API responses."""
        torrents = self._client.torrents_info()
        return [
            TorrentSummary(
                hash=torrent.hash,
                name=torrent.name,
                state=torrent.state,
                progress=float(torrent.progress),
            )
            for torrent in torrents
        ]
