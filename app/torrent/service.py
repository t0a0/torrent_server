"""qBittorrent service for adding magnet links and torrent files."""

from __future__ import annotations

import logging
import shutil
import threading
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from qbittorrent import Client
from qbittorrent.client import LoginRequired

from .config import (
    get_active_downloads_root,
    get_downloads_root,
    get_qbittorrent_password,
    get_qbittorrent_url,
    get_qbittorrent_username,
    get_qbit_global_upload_limit_bytes_per_sec,
)


@dataclass(frozen=True)
class QueuedTorrentStatus:
    """A single active torrent status row for /status and /canceldownload output."""

    hash: str
    name: str
    progress_percent: float
    state: str | None
    dlspeed_bytes_per_sec: int | None
    eta_seconds: int | None


@dataclass(frozen=True)
class CompletedTorrent:
    """Metadata about one torrent that has finished downloading."""

    hash: str
    name: str | None
    user_id: int | None
    content_path: Path | None
    content_is_directory: bool


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
        active_downloads_root: Path | None = None,
        completion_poll_interval_seconds: float = 30.0,
        on_torrent_completed: Callable[[CompletedTorrent], None] | None = None,
    ) -> None:
        self._logger = logging.getLogger(__name__)
        self._completion_poll_interval_seconds = max(completion_poll_interval_seconds, 1.0)
        self._downloads_root = (downloads_root or get_downloads_root()).resolve()
        self._active_downloads_root = (active_downloads_root or get_active_downloads_root()).resolve()
        self._client = Client(qbittorrent_url or get_qbittorrent_url())
        self._username = (
            qbittorrent_username if qbittorrent_username is not None else get_qbittorrent_username()
        )
        self._password = (
            qbittorrent_password if qbittorrent_password is not None else get_qbittorrent_password()
        )
        self._on_torrent_completed = on_torrent_completed

        self._apply_global_upload_limit()
        self._start_completion_cleanup_worker()

    def _apply_global_upload_limit(self) -> None:
        """Apply qBittorrent global upload speed limit from environment config."""
        upload_limit_bytes_per_sec = get_qbit_global_upload_limit_bytes_per_sec()
        if upload_limit_bytes_per_sec < 0:
            raise ValueError("QBIT_GLOBAL_UPLOAD_LIMIT_BYTES_PER_SEC must be >= 0")

        self._call_with_auth(
            self._client.set_preferences,
            up_limit=upload_limit_bytes_per_sec,
        )
        self._logger.info(
            "Applied qBittorrent global upload limit: %s bytes/sec",
            upload_limit_bytes_per_sec,
        )

    def _build_user_download_path(self, user_id: int) -> Path:
        """Return `activedownloads/<user_id>` path used by qBittorrent for active jobs."""
        return self._active_downloads_root / str(user_id)

    def start_download_from_file_bytes(self, user_id: int, torrent_file_bytes: bytes) -> None:
        """Queue torrent file bytes for download into `activedownloads/<user_id>` directory."""
        if not torrent_file_bytes:
            raise ValueError("torrent_file_bytes must not be empty")

        save_path = self._build_user_download_path(user_id)
        file_buffer = BytesIO(torrent_file_bytes)
        self._call_with_auth(self._client.download_from_file, file_buffer, savepath=str(save_path))

    def start_download_from_magnet_url(self, user_id: int, magnet_url: str) -> None:
        """Queue magnet link for download into `activedownloads/<user_id>` directory."""
        magnet = magnet_url.strip()
        if not magnet.startswith("magnet:"):
            raise ValueError("magnet_url must start with 'magnet:'")

        save_path = self._build_user_download_path(user_id)
        self._call_with_auth(self._client.download_from_link, magnet, savepath=str(save_path))

    def list_user_queued_torrents(self, user_id: int) -> list[QueuedTorrentStatus]:
        """Return active queued/downloading torrents for a specific user."""
        torrents = self._call_with_auth(self._client.torrents)
        if not isinstance(torrents, list):
            return []

        result: list[QueuedTorrentStatus] = []
        for torrent in torrents:
            if not isinstance(torrent, dict):
                continue

            if self._is_completed_torrent(torrent):
                continue

            name = torrent.get("name")
            if not isinstance(name, str) or not name:
                continue

            if not self._is_user_torrent(torrent=torrent, user_id=user_id):
                continue

            torrent_hash = torrent.get("hash")
            if not isinstance(torrent_hash, str) or not torrent_hash:
                continue

            progress = torrent.get("progress")
            if isinstance(progress, (int, float)):
                progress_ratio = max(0.0, min(float(progress), 1.0))
            else:
                progress_ratio = 0.0

            state = torrent.get("state") if isinstance(torrent.get("state"), str) else None
            dlspeed = torrent.get("dlspeed")
            eta = torrent.get("eta")

            result.append(
                QueuedTorrentStatus(
                    hash=torrent_hash,
                    name=name,
                    progress_percent=round(progress_ratio * 100.0, 1),
                    state=state,
                    dlspeed_bytes_per_sec=dlspeed if isinstance(dlspeed, int) else None,
                    eta_seconds=eta if isinstance(eta, int) else None,
                )
            )

        result.sort(key=lambda item: item.name.lower())
        return result

    def cancel_user_torrent(self, user_id: int, torrent_hash: str) -> bool:
        """Cancel an active torrent owned by user and remove downloaded files."""
        normalized_hash = torrent_hash.strip().lower()
        if not normalized_hash:
            return False

        active_torrents = self.list_user_queued_torrents(user_id)
        for torrent in active_torrents:
            if torrent.hash.lower() != normalized_hash:
                continue

            self._delete_torrent_and_files(torrent.hash)
            return True

        return False

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
        """Delete all completed torrents from queue, then move payload to downloads root."""
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

            torrent_name = torrent.get("name") if isinstance(torrent.get("name"), str) else None
            completed_content_path = self._extract_completed_content_path(torrent)
            user_id = self._extract_user_id_from_torrent(torrent)

            self._call_with_auth(self._client.delete, torrent_hash)
            self._logger.info("Deleted completed torrent '%s' to stop seeding", torrent_hash)

            moved_content_path = self._move_completed_payload_to_downloads(
                user_id=user_id,
                completed_content_path=completed_content_path,
            )
            completed_torrent = CompletedTorrent(
                hash=torrent_hash,
                name=torrent_name,
                user_id=user_id,
                content_path=moved_content_path,
                content_is_directory=moved_content_path.is_dir() if moved_content_path is not None else False,
            )
            self._notify_torrent_completed(completed_torrent)


    def _move_completed_payload_to_downloads(
        self,
        user_id: int | None,
        completed_content_path: Path | None,
    ) -> Path | None:
        """Move completed torrent payload from active root to downloads root."""
        if user_id is None or completed_content_path is None:
            return None

        try:
            resolved_source = completed_content_path.resolve()
        except OSError:
            return None

        if not resolved_source.exists():
            self._logger.warning("Completed payload path does not exist: %s", resolved_source)
            return None

        source_user_root = (self._active_downloads_root / str(user_id)).resolve()
        destination_user_root = (self._downloads_root / str(user_id)).resolve()

        if resolved_source == source_user_root:
            return None
        if source_user_root not in resolved_source.parents:
            self._logger.warning(
                "Skipping move for payload outside active user directory user_id=%s path=%s",
                user_id,
                resolved_source,
            )
            return None

        relative_payload_path = resolved_source.relative_to(source_user_root)
        destination_path = destination_user_root / relative_payload_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        if destination_path.exists():
            if destination_path.is_dir():
                shutil.rmtree(destination_path)
            else:
                destination_path.unlink()

        shutil.move(str(resolved_source), str(destination_path))
        return destination_path

    def _delete_torrent_and_files(self, torrent_hash: str) -> None:
        """Delete a torrent from qBittorrent queue and remove payload files."""
        if hasattr(self._client, "delete_permanently"):
            self._call_with_auth(self._client.delete_permanently, torrent_hash)
            return

        delete_method = self._client.delete
        try:
            self._call_with_auth(delete_method, torrent_hash, True)
            return
        except TypeError:
            pass

        for keyword in ("delete_files", "deleteFiles"):
            try:
                self._call_with_auth(delete_method, torrent_hash, **{keyword: True})
                return
            except TypeError:
                continue

        self._call_with_auth(delete_method, torrent_hash)

    def _notify_torrent_completed(self, torrent: CompletedTorrent) -> None:
        """Call optional completion callback without breaking cleanup loop."""
        if self._on_torrent_completed is None:
            return

        try:
            self._on_torrent_completed(torrent)
        except Exception:
            self._logger.exception("Failed to process completed torrent notification")

    def _extract_user_id_from_torrent(self, torrent: dict[str, Any]) -> int | None:
        """Infer Telegram user id from qBittorrent save path rooted at active downloads dir."""
        save_path = torrent.get("save_path")
        if not isinstance(save_path, str) or not save_path:
            return None

        try:
            resolved_save_path = Path(save_path).resolve()
        except OSError:
            return None

        if resolved_save_path == self._active_downloads_root:
            return None
        if self._active_downloads_root not in resolved_save_path.parents:
            return None

        relative_parts = resolved_save_path.relative_to(self._active_downloads_root).parts
        if not relative_parts:
            return None

        try:
            return int(relative_parts[0])
        except ValueError:
            return None

    def _extract_completed_content_path(self, torrent: dict[str, Any]) -> Path | None:
        """Resolve finished payload path from qBittorrent `content_path` when available."""
        content_path = torrent.get("content_path")
        if not isinstance(content_path, str) or not content_path:
            return None

        try:
            resolved_content_path = Path(content_path).resolve()
        except OSError:
            return None

        if resolved_content_path == self._active_downloads_root:
            return None
        if self._active_downloads_root not in resolved_content_path.parents:
            return None

        return resolved_content_path


    def _is_user_torrent(self, torrent: dict[str, Any], user_id: int) -> bool:
        """Check whether torrent save_path belongs to the target Telegram user directory."""
        save_path = torrent.get("save_path")
        if not isinstance(save_path, str) or not save_path:
            return False

        user_download_path = self._build_user_download_path(user_id).resolve()
        try:
            torrent_save_path = Path(save_path).resolve()
        except OSError:
            return False

        return torrent_save_path == user_download_path or user_download_path in torrent_save_path.parents

    def _is_completed_torrent(self, torrent: dict[str, Any]) -> bool:
        """Return True when torrent is in a completed/upload state."""
        state = torrent.get("state")
        return state in self._FINISHED_STATES
