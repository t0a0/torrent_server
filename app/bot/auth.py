"""In-memory auth and access-token services for Phase 1 bot commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
        owner_username: str | None = None,
    ) -> None:
        self._owner_user_id = owner_user_id
        self._owner_username = self._normalize_username(owner_username)
        self._tokens: dict[str, datetime] = {}
        self._whitelist: dict[int, WhitelistedUser] = {}

        if owner_user_id is not None:
            self._whitelist[owner_user_id] = WhitelistedUser(
                user_id=owner_user_id,
                username_at_authentication=self._owner_username,
            )

    @staticmethod
    def _normalize_username(username: str | None) -> str | None:
        if not username:
            return None
        normalized = username.strip().lstrip("@").lower()
        return normalized or None

    def _purge_expired_tokens(self) -> None:
        now = datetime.now(UTC)
        expired_tokens = [token for token, expires_at in self._tokens.items() if expires_at <= now]
        for token in expired_tokens:
            self._tokens.pop(token, None)

    def is_admin(self, user_id: int, username: str | None) -> bool:
        if self._owner_user_id is not None and user_id == self._owner_user_id:
            return True
        normalized = self._normalize_username(username)
        return normalized is not None and normalized == self._owner_username

    def is_whitelisted(self, user_id: int) -> bool:
        return user_id in self._whitelist

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
        self._whitelist[user_id] = WhitelistedUser(
            user_id=user_id,
            username_at_authentication=self._normalize_username(username),
        )
        return True

    def remove_user(self, user_id: int) -> bool:
        return self._whitelist.pop(user_id, None) is not None

    def list_whitelisted_users(self) -> list[WhitelistedUser]:
        return sorted(self._whitelist.values(), key=lambda item: item.user_id)
