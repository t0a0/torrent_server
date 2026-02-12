from __future__ import annotations

from app.config import Settings
from app.security.auth import is_allowed_telegram_user


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="token",
        telegram_allowed_user_ids=frozenset({123, 999}),
        qbittorrent_base_url="http://qbittorrent:8080",
        qbittorrent_username="admin",
        qbittorrent_password="pass",
        qbittorrent_verify_certificate=False,
        sqlite_path="./data/db.sqlite3",
        download_base_url="https://downloads.example.com",
        download_token_secret="secret",
        download_token_ttl_seconds=60,
    )


def test_allowlist_allows_known_user() -> None:
    settings = _settings()
    assert is_allowed_telegram_user(123, settings)


def test_allowlist_rejects_unknown_user() -> None:
    settings = _settings()
    assert not is_allowed_telegram_user(555, settings)
