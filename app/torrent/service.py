"""qBittorrent service for adding magnet links and torrent files."""

from __future__ import annotations

import logging
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any

from qbittorrent import Client
from qbittorrent.client import LoginRequired

from .config import (
    get_downloads_root,
    get_qbittorrent_password,
    get_qbittorrent_url,
    get_qbittorrent_username,
)


class TorrentService:
    """Thin wrapper around python-qbittorrent with per-user save directories."""

    _FINISHED_STATES = {
        "uploading",
        "stalledUP",
        "queuedUP",
        "forcedUP",
        "checkingUP",
    }

    def __init__(
        self,
        qbittorrent_url: str | None = None,
        qbittorrent_username: str | None = None,
        qbittorrent_password: str | None = None,
        downloads_root: Path | None = None,
        completion_poll_interval_seconds: float = 30.0,
    ) -> None:
        self._logger = logging.getLogger(__name__)
        self._completion_poll_interval_seconds = max(completion_poll_interval_seconds, 1.0)
        self._downloads_root = downloads_root or get_downloads_root()
        self._client = Client(qbittorrent_url or get_qbittorrent_url())
        self._username = (
            qbittorrent_username if qbittorrent_username is not None else get_qbittorrent_username()
        )
        self._password = (
            qbittorrent_password if qbittorrent_password is not None else get_qbittorrent_password()
        )

        self._start_completion_cleanup_worker()

    def _build_user_download_path(self, user_id: int) -> Path:
        """Return `downloads/<user_id>` path and avoid creating root-owned directories.

        In Docker deployments, the bot and qBittorrent usually run as different users.
        If the bot eagerly creates `downloads/<user_id>`, qBittorrent can fail writing
        payload files with `Permission denied` because it does not own that directory.
        We therefore pass the path to qBittorrent without creating it here.
        """
        return self._downloads_root / str(user_id)

    def start_download_from_file_bytes(self, user_id: int, torrent_file_bytes: bytes) -> None:
        """Queue torrent file bytes for download into `downloads/<user_id>` directory."""
        if not torrent_file_bytes:
            raise ValueError("torrent_file_bytes must not be empty")

        save_path = self._build_user_download_path(user_id)
        file_buffer = BytesIO(torrent_file_bytes)
        self._call_with_auth(self._client.download_from_file, file_buffer, savepath=str(save_path))

    def start_download_from_magnet_url(self, user_id: int, magnet_url: str) -> None:
        """Queue magnet link for download into `downloads/<user_id>` directory."""
        magnet = magnet_url.strip()
        if not magnet.startswith("magnet:"):
            raise ValueError("magnet_url must start with 'magnet:'")

        save_path = self._build_user_download_path(user_id)
        self._call_with_auth(self._client.download_from_link, magnet, savepath=str(save_path))

    def _login(self) -> None:
        """Login to qBittorrent Web UI using configured credentials."""
        if not self._username or not self._password:
            raise ValueError(
                "qBittorrent requires authentication, but QBITTORRENT_USERNAME and "
                "QBITTORRENT_PASSWORD are not fully configured."
            )

        self._client.login(username=self._username, password=self._password)

    def _call_with_auth(self, method: Any, *args: Any, **kwargs: Any) -> Any:
        """Call qBittorrent API method and re-authenticate if session expired."""
        try:
            return method(*args, **kwargs)
        except LoginRequired:
            self._logger.info("qBittorrent session expired. Re-authenticating.")
            self._login()
            return method(*args, **kwargs)

    def _start_completion_cleanup_worker(self) -> None:
        """Run one daemon background worker that removes completed torrents from queue.

        The worker loop is intentionally long-lived and exits only when the Python process
        shuts down. Because the thread is daemonized, it is automatically terminated on
        process exit and does not block application shutdown.
        """
        threading.Thread(target=self._completion_cleanup_loop, daemon=True).start()

    def _completion_cleanup_loop(self) -> None:
        """Continuously remove torrents that have finished downloading."""
        while True:
            try:
                self._delete_completed_torrents()
            except Exception:
                self._logger.exception("Failed while cleaning up completed torrents")
            time.sleep(self._completion_poll_interval_seconds)

    def _delete_completed_torrents(self) -> None:
        """Delete all completed torrents from queue and keep files on disk."""
        torrents = self._call_with_auth(self._client.torrents)
        if not isinstance(torrents, list):
            return

        for torrent in torrents:
            if not isinstance(torrent, dict):
                continue
            if not self._is_completed_torrent(torrent):
                continue

            torrent_hash = torrent.get("hash")
            if not isinstance(torrent_hash, str) or not torrent_hash:
                continue

            # `python-qbittorrent` client signatures vary across versions
            # (`hash` vs `hashes`). Pass arguments positionally to stay compatible.
            self._call_with_auth(self._client.delete, torrent_hash, False)
            self._logger.info("Deleted completed torrent '%s' to stop seeding", torrent_hash)

    def _is_completed_torrent(self, torrent: dict[str, Any]) -> bool:
        """Return True when torrent is in a completed/upload state."""
        state = torrent.get("state")
        return state in self._FINISHED_STATES
