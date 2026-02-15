"""SQLite-backed auth whitelist and in-memory access-token services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
import secrets


@dataclass(slots=True, frozen=True)
class WhitelistedUser:
    """Represents a user that has successfully authenticated."""

    user_id: int
    username_at_authentication: str | None


class AuthService:
    """Holds admin config, temporary access tokens and whitelisted users."""

    _TOKEN_TTL = timedelta(minutes=30)

    def __init__(
        self,
        owner_user_id: int | None = None,
        db_path: str = "auth.db",
    ) -> None:
        self._owner_user_id = owner_user_id
        self._db_path = Path(db_path)
        self._tokens: dict[str, datetime] = {}
        self._initialize_database()

    def _initialize_database(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS whitelisted_users (
                    user_id INTEGER PRIMARY KEY,
                    username_at_authentication TEXT
                )
                """
            )
            connection.commit()

    def _purge_expired_tokens(self) -> None:
        now = datetime.now(UTC)
        expired_tokens = [token for token, expires_at in self._tokens.items() if expires_at <= now]
        for token in expired_tokens:
            self._tokens.pop(token, None)

    def is_admin(self, user_id: int) -> bool:
        return self._owner_user_id is not None and user_id == self._owner_user_id

    def is_whitelisted(self, user_id: int) -> bool:
        if self.is_admin(user_id):
            return True

        with sqlite3.connect(self._db_path) as connection:
            row = connection.execute(
                "SELECT 1 FROM whitelisted_users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return row is not None

    def generate_access_token(self) -> str:
        self._purge_expired_tokens()
        token = secrets.token_urlsafe(32)
        self._tokens[token] = datetime.now(UTC) + self._TOKEN_TTL
        return token

    def authenticate_user(self, token: str, user_id: int, username: str | None) -> bool:
        self._purge_expired_tokens()
        expires_at = self._tokens.get(token)
        now = datetime.now(UTC)
        if expires_at is None or expires_at <= now:
            self._tokens.pop(token, None)
            return False

        self._tokens.pop(token, None)
        with sqlite3.connect(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO whitelisted_users(user_id, username_at_authentication)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username_at_authentication = excluded.username_at_authentication
                """,
                (user_id, username),
            )
            connection.commit()
        return True

    def remove_user(self, user_id: int) -> bool:
        with sqlite3.connect(self._db_path) as connection:
            cursor = connection.execute(
                "DELETE FROM whitelisted_users WHERE user_id = ?",
                (user_id,),
            )
            connection.commit()
        return cursor.rowcount > 0

    def list_whitelisted_users(self) -> list[WhitelistedUser]:
        with sqlite3.connect(self._db_path) as connection:
            rows = connection.execute(
                """
                SELECT user_id, username_at_authentication
                FROM whitelisted_users
                ORDER BY user_id ASC
                """
            ).fetchall()

        return [
            WhitelistedUser(
                user_id=row[0],
                username_at_authentication=row[1],
            )
            for row in rows
        ]
