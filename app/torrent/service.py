"""qBittorrent service for adding magnet links and torrent files."""

from __future__ import annotations

import logging
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any

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
        completion_poll_interval_seconds: float = 5.0,
    ) -> None:
        self._logger = logging.getLogger(__name__)
        self._completion_poll_interval_seconds = max(completion_poll_interval_seconds, 1.0)
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
        known_hashes = self._list_torrent_hashes_for_save_path(save_path)
        file_buffer = BytesIO(torrent_file_bytes)
        self._client.download_from_file(file_buffer, savepath=str(save_path))
        self._start_auto_delete_thread(save_path=save_path, known_hashes=known_hashes)

    def start_download_from_magnet_url(self, user_id: int, magnet_url: str) -> None:
        """Queue magnet link for download into `downloads/<user_id>` directory."""
        magnet = magnet_url.strip()
        if not magnet.startswith("magnet:"):
            raise ValueError("magnet_url must start with 'magnet:'")

        save_path = self._build_user_download_path(user_id)
        known_hashes = self._list_torrent_hashes_for_save_path(save_path)
        self._client.download_from_link(magnet, savepath=str(save_path))
        self._start_auto_delete_thread(save_path=save_path, known_hashes=known_hashes)

    def _list_torrents(self) -> list[dict[str, Any]]:
        """Read torrent list from client while supporting different python-qbittorrent variants."""
        for method_name in ("torrents_info", "torrents"):
            method = getattr(self._client, method_name, None)
            if callable(method):
                torrents = method()
                if isinstance(torrents, list):
                    return [torrent for torrent in torrents if isinstance(torrent, dict)]
        return []

    @staticmethod
    def _normalize_path(path: Path | str) -> str:
        """Normalize save paths for stable comparison across qBittorrent responses."""
        return str(path).rstrip("/\\")

    def _list_torrent_hashes_for_save_path(self, save_path: Path) -> set[str]:
        """Collect torrent hashes that currently belong to a save path."""
        normalized_save_path = self._normalize_path(save_path)
        hashes: set[str] = set()

        for torrent in self._list_torrents():
            torrent_save_path = torrent.get("save_path")
            if torrent_save_path is None:
                continue
            if self._normalize_path(torrent_save_path) != normalized_save_path:
                continue
            torrent_hash = torrent.get("hash")
            if isinstance(torrent_hash, str) and torrent_hash:
                hashes.add(torrent_hash)

        return hashes

    def _start_auto_delete_thread(self, save_path: Path, known_hashes: set[str]) -> None:
        """Start a detached worker that deletes a torrent after completion."""
        threading.Thread(
            target=self._delete_when_completed,
            kwargs={"save_path": save_path, "known_hashes": known_hashes},
            daemon=True,
        ).start()

    def _delete_when_completed(self, save_path: Path, known_hashes: set[str]) -> None:
        """Watch a newly added torrent and remove it once download reaches 100%."""
        torrent_hash = self._wait_for_new_torrent_hash(save_path=save_path, known_hashes=known_hashes)
        if torrent_hash is None:
            self._logger.warning(
                "Could not identify newly added torrent for save path '%s'; skipping auto-delete",
                save_path,
            )
            return

        if not self._wait_until_completed(torrent_hash):
            self._logger.warning(
                "Timed out waiting for torrent '%s' completion; skipping auto-delete",
                torrent_hash,
            )
            return

        self._delete_torrent(torrent_hash)

    def _wait_for_new_torrent_hash(self, save_path: Path, known_hashes: set[str], timeout_seconds: float = 120.0) -> str | None:
        """Find hash of the torrent that was just added for the given save path."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            current_hashes = self._list_torrent_hashes_for_save_path(save_path)
            new_hashes = current_hashes - known_hashes
            if new_hashes:
                return next(iter(new_hashes))
            time.sleep(self._completion_poll_interval_seconds)
        return None

    def _wait_until_completed(self, torrent_hash: str, timeout_seconds: float = 604800.0) -> bool:
        """Poll torrent state until download completion or timeout."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            torrent = self._find_torrent_by_hash(torrent_hash)
            if torrent is None:
                return False
            if self._is_completed_torrent(torrent):
                return True
            time.sleep(self._completion_poll_interval_seconds)
        return False

    def _find_torrent_by_hash(self, torrent_hash: str) -> dict[str, Any] | None:
        """Return a torrent dictionary by hash."""
        for torrent in self._list_torrents():
            if torrent.get("hash") == torrent_hash:
                return torrent
        return None

    @staticmethod
    def _is_completed_torrent(torrent: dict[str, Any]) -> bool:
        """Detect if a torrent has finished downloading and is in an upload/checking state."""
        progress = torrent.get("progress")
        if isinstance(progress, (float, int)) and progress >= 1:
            return True

        amount_left = torrent.get("amount_left")
        if isinstance(amount_left, (float, int)) and amount_left <= 0:
            return True

        state = torrent.get("state")
        return state in {
            "uploading",
            "stalledUP",
            "queuedUP",
            "forcedUP",
            "checkingUP",
        }

    def _delete_torrent(self, torrent_hash: str) -> None:
        """Delete torrent from qBittorrent queue while keeping downloaded files on disk."""
        for method_name in ("delete", "torrents_delete"):
            method = getattr(self._client, method_name, None)
            if not callable(method):
                continue

            try:
                method(hashes=torrent_hash, delete_files=False)
            except TypeError:
                method(torrent_hash)
            self._logger.info("Deleted torrent '%s' after completion to stop seeding", torrent_hash)
            return

        self._logger.warning("Unable to delete torrent '%s': unsupported python-qbittorrent client API", torrent_hash)
