"""SQLite-backed storage for completed torrent records."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import threading
import time


@dataclass(frozen=True)
class CompletedDownloadRecord:
    infohash: str
    user_id: int
    content_path: str
    torrent_name: str | None
    created_at_epoch_seconds: int


class CompletedDownloadStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self._db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS completed_torrents (
                    infohash TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    content_path TEXT NOT NULL,
                    torrent_name TEXT,
                    created_at_epoch_seconds INTEGER NOT NULL,
                    PRIMARY KEY (infohash, user_id)
                )
                """
            )
            connection.commit()

    def upsert_completed(
        self,
        *,
        infohash: str,
        user_id: int,
        content_path: str,
        torrent_name: str | None,
    ) -> None:
        now = int(time.time())
        with self._lock, sqlite3.connect(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO completed_torrents (infohash, user_id, content_path, torrent_name, created_at_epoch_seconds)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(infohash, user_id) DO UPDATE SET
                    content_path=excluded.content_path,
                    torrent_name=excluded.torrent_name,
                    created_at_epoch_seconds=excluded.created_at_epoch_seconds
                """,
                (infohash, user_id, content_path, torrent_name, now),
            )
            connection.commit()

    def find_completed(self, *, infohash: str, user_id: int) -> CompletedDownloadRecord | None:
        with self._lock, sqlite3.connect(self._db_path) as connection:
            cursor = connection.execute(
                """
                SELECT infohash, user_id, content_path, torrent_name, created_at_epoch_seconds
                FROM completed_torrents
                WHERE infohash = ? AND user_id = ?
                """,
                (infohash, user_id),
            )
            row = cursor.fetchone()

        if row is None:
            return None

        return CompletedDownloadRecord(
            infohash=row[0],
            user_id=row[1],
            content_path=row[2],
            torrent_name=row[3],
            created_at_epoch_seconds=row[4],
        )

    def delete_completed(self, *, infohash: str, user_id: int) -> None:
        with self._lock, sqlite3.connect(self._db_path) as connection:
            connection.execute(
                "DELETE FROM completed_torrents WHERE infohash = ? AND user_id = ?",
                (infohash, user_id),
            )
            connection.commit()

