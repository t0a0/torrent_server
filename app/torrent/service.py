"""qBittorrent service for adding magnet links and torrent files."""

from __future__ import annotations

import logging
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import requests

from qbittorrent import Client
from qbittorrent.client import LoginRequired

from .config import (
    get_active_downloads_root,
    get_download_records_db_path,
    get_downloads_root,
    get_finished_download_retention_days,
    get_finished_downloads_root,
    get_qbittorrent_password,
    get_qbittorrent_url,
    get_qbittorrent_username,
    get_qbit_global_upload_limit_bytes_per_sec,
)
from .download_records import DownloadRecordRepository


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


@dataclass(frozen=True)
class FailedTorrent:
    """Metadata about one torrent that entered an error state."""

    hash: str
    name: str | None
    user_id: int | None
    state: str | None


class TorrentService:
    """Thin wrapper around python-qbittorrent with per-user save directories."""

    _FINISHED_STATES = {
        "uploading",
        "stalledUP",
        "queuedUP",
        "forcedUP",
        "checkingUP",
    }
    _FAILED_STATES = {
        "error",
        "missingFiles",
    }
    def __init__(
        self,
        qbittorrent_url: str | None = None,
        qbittorrent_username: str | None = None,
        qbittorrent_password: str | None = None,
        finished_downloads_root: Path | None = None,
        active_downloads_root: Path | None = None,
        downloads_root: Path | None = None,
        default_owner_user_id: int | None = None,
        completion_poll_interval_seconds: float = 30.0,
        retention_poll_interval_seconds: float = 60.0 * 60.0,
        on_torrent_completed: Callable[[CompletedTorrent], None] | None = None,
        on_torrent_failed: Callable[[FailedTorrent], None] | None = None,
    ) -> None:
        self._logger = logging.getLogger(__name__)
        self._completion_poll_interval_seconds = max(completion_poll_interval_seconds, 1.0)
        self._retention_poll_interval_seconds = max(retention_poll_interval_seconds, 1.0)
        self._finished_downloads_root = (finished_downloads_root or get_finished_downloads_root()).resolve()
        self._active_downloads_root = (active_downloads_root or get_active_downloads_root()).resolve()
        self._downloads_root = (downloads_root or get_downloads_root()).resolve()
        self._default_owner_user_id = default_owner_user_id
        self._client = Client(qbittorrent_url or get_qbittorrent_url())
        self._username = (
            qbittorrent_username if qbittorrent_username is not None else get_qbittorrent_username()
        )
        self._password = (
            qbittorrent_password if qbittorrent_password is not None else get_qbittorrent_password()
        )
        self._on_torrent_completed = on_torrent_completed
        self._on_torrent_failed = on_torrent_failed
        self._download_records = DownloadRecordRepository(get_download_records_db_path())
        self._download_retention_days = get_finished_download_retention_days()
        if self._download_retention_days <= 0:
            raise ValueError("FINISHED_DOWNLOAD_RETENTION_DAYS must be > 0")

        self._apply_global_upload_limit()
        self._start_completion_cleanup_worker()
        self._start_finished_downloads_retention_worker()

    def _apply_global_upload_limit(self) -> None:
        """Apply qBittorrent global upload speed limit from environment config."""
        upload_limit_bytes_per_sec = get_qbit_global_upload_limit_bytes_per_sec()
        if upload_limit_bytes_per_sec < 0:
            raise ValueError("Global upload limit must be >= 0")

        self._call_with_auth(
            self._client.set_preferences,
            up_limit=upload_limit_bytes_per_sec,
        )
        self._logger.info(
            "Applied qBittorrent global upload limit: %s bytes/sec",
            upload_limit_bytes_per_sec,
        )

    def _build_user_download_path(self, user_id: int) -> Path:
        """Return `active_downloads/<user_id>` path without eagerly creating folders."""
        return self._active_downloads_root / str(user_id)

    def start_download_from_file_bytes(self, user_id: int, torrent_file_bytes: bytes) -> None:
        """Queue torrent file bytes for download into `active_downloads/<user_id>`."""
        if not torrent_file_bytes:
            raise ValueError("torrent_file_bytes must not be empty")

        save_path = self._build_user_download_path(user_id)
        file_buffer = BytesIO(torrent_file_bytes)
        self._call_with_auth(self._client.download_from_file, file_buffer, savepath=str(save_path))

    def start_download_from_magnet_url(self, user_id: int, magnet_url: str) -> None:
        """Queue magnet link for download into `active_downloads/<user_id>`."""
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

    def is_torrent_already_queued(self, infohash: str) -> bool:
        """Return True when a torrent with the provided infohash already exists in qBittorrent."""
        normalized_hash = infohash.strip().lower()
        if not normalized_hash:
            return False

        torrents = self._call_with_auth(self._client.torrents)
        if not isinstance(torrents, list):
            return False

        for torrent in torrents:
            if not isinstance(torrent, dict):
                continue

            torrent_hash = torrent.get("hash")
            if not isinstance(torrent_hash, str):
                continue

            if torrent_hash.strip().lower() == normalized_hash:
                return True

        return False

    def _login(self) -> None:
        """Login to qBittorrent Web UI using configured credentials.

        We deliberately bypass ``Client.login``'s response check. The bundled
        python-qbittorrent treats only the legacy ``"Ok."`` body as success,
        whereas qBittorrent 5.x answers a successful login with ``204 No
        Content`` (empty body). That mismatch leaves the client permanently
        unauthenticated and every call raising ``LoginRequired``. Keying
        success off the HTTP status keeps us compatible across versions.
        """
        if not self._username or not self._password:
            raise ValueError(
                "qBittorrent requires authentication, but QBITTORRENT_USERNAME and "
                "QBITTORRENT_PASSWORD are not fully configured."
            )

        session = requests.Session()
        response = session.post(
            self._client.url + "auth/login",
            data={"username": self._username, "password": self._password},
            verify=self._client.verify,
        )
        if response.status_code >= 400 or response.text.strip() == "Fails.":
            raise LoginRequired(
                f"qBittorrent login failed ({response.status_code}): "
                f"{response.text.strip()!r}"
            )

        self._client.session = session
        self._client._is_authenticated = True

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

    def _start_finished_downloads_retention_worker(self) -> None:
        """Run one daemon worker that removes expired finished downloads."""
        threading.Thread(target=self._finished_downloads_retention_loop, daemon=True).start()

    def _finished_downloads_retention_loop(self) -> None:
        """Continuously remove finished downloads older than retention threshold."""
        while True:
            try:
                self._cleanup_expired_finished_downloads()
            except Exception:
                self._logger.exception("Failed while cleaning up expired finished downloads")
            time.sleep(self._retention_poll_interval_seconds)

    def _delete_completed_torrents(self) -> None:
        """Delete all completed torrents from queue and keep files on disk."""
        torrents = self._call_with_auth(self._client.torrents)
        if not isinstance(torrents, list):
            return

        for torrent in torrents:
            if not isinstance(torrent, dict):
                continue

            if self._is_failed_torrent(torrent):
                torrent_hash = torrent.get("hash")
                if not isinstance(torrent_hash, str) or not torrent_hash:
                    continue

                failed_torrent = FailedTorrent(
                    hash=torrent_hash,
                    name=torrent.get("name") if isinstance(torrent.get("name"), str) else None,
                    user_id=self._extract_user_id_from_torrent(torrent),
                    state=torrent.get("state") if isinstance(torrent.get("state"), str) else None,
                )
                self._notify_torrent_failed(failed_torrent)
                self._delete_torrent_and_files(torrent_hash)
                self._logger.info(
                    "Deleted failed torrent '%s' and attempted to remove partial files",
                    torrent_hash,
                )
                continue

            if not self._is_completed_torrent(torrent):
                continue

            torrent_hash = torrent.get("hash")
            if not isinstance(torrent_hash, str) or not torrent_hash:
                continue

            torrent_name = torrent.get("name") if isinstance(torrent.get("name"), str) else None
            completed_torrent_user_id = self._extract_user_id_from_torrent(torrent)
            if completed_torrent_user_id is None and self._default_owner_user_id is not None:
                completed_torrent_user_id = self._default_owner_user_id
                self._logger.info(
                    "Torrent '%s' has no user id in its save path; attributing to owner %s",
                    torrent_hash,
                    self._default_owner_user_id,
                )
            completed_content_path = self._extract_completed_content_path(torrent)
            moved_content_path = self._move_completed_payload_to_downloads(
                completed_content_path=completed_content_path,
                user_id=completed_torrent_user_id,
            )
            completed_torrent = CompletedTorrent(
                hash=torrent_hash,
                name=torrent_name,
                user_id=completed_torrent_user_id,
                content_path=moved_content_path,
                content_is_directory=moved_content_path.is_dir() if moved_content_path is not None else False,
            )
            if completed_torrent_user_id is not None and self._is_within_finished_downloads_root(moved_content_path):
                self._download_records.add_record(
                    user_id=completed_torrent_user_id,
                    content_path=moved_content_path,
                    torrent_hash=torrent_hash,
                )
            self._notify_torrent_completed(completed_torrent)

            self._call_with_auth(self._client.delete, torrent_hash)
            self._logger.info("Deleted completed torrent '%s' to stop seeding", torrent_hash)

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

    def _notify_torrent_failed(self, torrent: FailedTorrent) -> None:
        """Call optional failure callback without breaking cleanup loop."""
        if self._on_torrent_failed is None:
            return

        try:
            self._on_torrent_failed(torrent)
        except Exception:
            self._logger.exception("Failed to process failed torrent notification")

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
        """Resolve finished payload path from qBittorrent `content_path` when available.

        Accepts payloads under `active_downloads` (bot-queued) as well as the broader
        `downloads_root` (queued directly via the qBittorrent Web UI), but never the
        finished-downloads destination, so already-moved files are not re-processed.
        """
        content_path = torrent.get("content_path")
        if not isinstance(content_path, str) or not content_path:
            return None

        try:
            resolved_content_path = Path(content_path).resolve()
        except OSError:
            return None

        if not self._is_within_managed_downloads(resolved_content_path):
            return None

        return resolved_content_path

    def _is_within_managed_downloads(self, content_path: Path) -> bool:
        """Return True when a payload path is eligible to be moved into finished downloads."""
        if content_path in (
            self._active_downloads_root,
            self._downloads_root,
            self._finished_downloads_root,
        ):
            return False

        if self._finished_downloads_root in content_path.parents:
            return False

        return (
            self._active_downloads_root in content_path.parents
            or self._downloads_root in content_path.parents
        )


    def _move_completed_payload_to_downloads(
        self,
        completed_content_path: Path | None,
        user_id: int | None,
    ) -> Path | None:
        """Move completed payload from active root into finished downloads root."""
        if completed_content_path is None or user_id is None:
            return completed_content_path

        destination_user_root = (self._finished_downloads_root / str(user_id)).resolve()
        destination_user_root.mkdir(parents=True, exist_ok=True)

        destination_path = destination_user_root / completed_content_path.name
        if destination_path.exists():
            destination_path = destination_user_root / f"{int(time.time())}_{completed_content_path.name}"

        try:
            moved_path = Path(shutil.move(str(completed_content_path), str(destination_path))).resolve()
        except (OSError, shutil.Error):
            self._logger.exception(
                "Failed to move completed payload '%s' to '%s'",
                completed_content_path,
                destination_path,
            )
            return completed_content_path

        return moved_path

    def _cleanup_expired_finished_downloads(self) -> None:
        """Delete stale finished-download payloads and their SQLite records."""
        retention_cutoff_timestamp = int(
            (datetime.now(timezone.utc) - timedelta(days=self._download_retention_days)).timestamp()
        )
        all_records = self._download_records.get_all_records()
        for record in all_records:
            if record.moved_at_unix_seconds > retention_cutoff_timestamp:
                continue

            content_path = record.content_path
            if not self._is_within_finished_downloads_root(content_path):
                self._logger.warning(
                    "Deleting download record id=%s with out-of-scope path '%s'",
                    record.id,
                    content_path,
                )
                self._download_records.delete_record(record.id)
                continue

            if not content_path.exists():
                self._download_records.delete_record(record.id)
                continue

            try:
                if content_path.is_dir():
                    shutil.rmtree(content_path)
                else:
                    content_path.unlink()
            except OSError:
                self._logger.exception(
                    "Failed to delete expired finished download '%s' for record id=%s",
                    content_path,
                    record.id,
                )
                continue

            self._download_records.delete_record(record.id)

    def _is_within_finished_downloads_root(self, content_path: Path | None) -> bool:
        """Return True when a path resolves under finished downloads root."""
        if content_path is None:
            return False
        try:
            resolved_content_path = content_path.resolve()
        except OSError:
            return False

        if resolved_content_path == self._finished_downloads_root:
            return False
        return self._finished_downloads_root in resolved_content_path.parents


    def _is_user_torrent(self, torrent: dict[str, Any], user_id: int) -> bool:
        """Check whether torrent save_path belongs to target user under active root."""
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

    def _is_failed_torrent(self, torrent: dict[str, Any]) -> bool:
        """Return True when torrent is in a known failure state."""
        state = torrent.get("state")
        return state in self._FAILED_STATES
