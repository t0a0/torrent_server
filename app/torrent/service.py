"""qBittorrent service for adding magnet links and torrent files."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from qbittorrent import Client

from .config import (
    get_downloads_root,
    get_qbittorrent_password,
    get_qbittorrent_url,
    get_qbittorrent_username,
)


class TorrentService:
    """Thin wrapper around python-qbittorrent with per-user save directories."""

    def __init__(
        self,
        qbittorrent_url: str | None = None,
        qbittorrent_username: str | None = None,
        qbittorrent_password: str | None = None,
        downloads_root: Path | None = None,
    ) -> None:
        self._downloads_root = downloads_root or get_downloads_root()
        self._client = Client(qbittorrent_url or get_qbittorrent_url())

        username = qbittorrent_username if qbittorrent_username is not None else get_qbittorrent_username()
        password = qbittorrent_password if qbittorrent_password is not None else get_qbittorrent_password()
        if username and password:
            self._client.login(username=username, password=password)

    def _build_user_download_path(self, user_id: int) -> Path:
        """Create and return `downloads/<user_id>` directory."""
        user_download_path = self._downloads_root / str(user_id)
        user_download_path.mkdir(parents=True, exist_ok=True)
        return user_download_path

    def start_download_from_file_bytes(self, user_id: int, torrent_file_bytes: bytes) -> None:
        """Queue torrent file bytes for download into `downloads/<user_id>` directory."""
        if not torrent_file_bytes:
            raise ValueError("torrent_file_bytes must not be empty")

        save_path = self._build_user_download_path(user_id)
        file_buffer = BytesIO(torrent_file_bytes)
        self._client.download_from_file(file_buffer, savepath=str(save_path))

    def start_download_from_magnet_url(self, user_id: int, magnet_url: str) -> None:
        """Queue magnet link for download into `downloads/<user_id>` directory."""
        magnet = magnet_url.strip()
        if not magnet.startswith("magnet:"):
            raise ValueError("magnet_url must start with 'magnet:'")

        save_path = self._build_user_download_path(user_id)
        self._client.download_from_link(magnet, savepath=str(save_path))
