"""Application entrypoint scaffold."""

from __future__ import annotations

from app.config import load_settings
from app.services.qbittorrent_client import QBittorrentClient


def create_qbittorrent_client() -> QBittorrentClient:
    """Create and authenticate a qBittorrent API client from env config."""
    settings = load_settings()
    client = QBittorrentClient(settings)
    client.login()
    return client


if __name__ == "__main__":
    create_qbittorrent_client()
    print("qBittorrent client initialized successfully.")
