"""SQLite storage for finished-download retention records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class DownloadRecord:
    """One retained finished-download record row."""

    id: int
    user_id: int
    content_path: Path
    moved_at_unix_seconds: int
    torrent_hash: str | None


class DownloadRecordRepository:
    """Persist and query per-user finished-download records."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path.resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS download_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    content_path TEXT NOT NULL,
                    moved_at_unix_seconds INTEGER NOT NULL,
                    torrent_hash TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_download_records_moved_at
                ON download_records (moved_at_unix_seconds)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_download_records_user_id
                ON download_records (user_id)
                """
            )

    def add_record(self, user_id: int, content_path: Path, torrent_hash: str | None) -> None:
        moved_at_unix_seconds = int(datetime.now(timezone.utc).timestamp())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO download_records (user_id, content_path, moved_at_unix_seconds, torrent_hash)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, str(content_path), moved_at_unix_seconds, torrent_hash),
            )

    def get_all_records(self) -> list[DownloadRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, content_path, moved_at_unix_seconds, torrent_hash
                FROM download_records
                ORDER BY moved_at_unix_seconds ASC, id ASC
                """
            ).fetchall()

        return [
            DownloadRecord(
                id=int(row["id"]),
                user_id=int(row["user_id"]),
                content_path=Path(str(row["content_path"])),
                moved_at_unix_seconds=int(row["moved_at_unix_seconds"]),
                torrent_hash=str(row["torrent_hash"]) if row["torrent_hash"] is not None else None,
            )
            for row in rows
        ]

    def delete_record(self, record_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM download_records WHERE id = ?", (record_id,))
