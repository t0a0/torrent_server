from __future__ import annotations

import pytest

from app.config import Settings
from app.security.signing import TokenError, create_download_token, parse_download_token


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="token",
        telegram_allowed_user_ids=frozenset({123}),
        qbittorrent_base_url="http://qbittorrent:8080",
        qbittorrent_username="admin",
        qbittorrent_password="pass",
        qbittorrent_verify_certificate=False,
        sqlite_path="./data/db.sqlite3",
        download_base_url="https://downloads.example.com",
        download_token_secret="secret",
        download_token_ttl_seconds=60,
    )


def test_create_and_parse_download_token() -> None:
    settings = _settings()
    token = create_download_token("abc123", settings=settings, now=1_700_000_000)

    payload = parse_download_token(token=token, settings=settings, now=1_700_000_010)

    assert payload.torrent_id == "abc123"


def test_parse_download_token_rejects_tampering() -> None:
    settings = _settings()
    token = create_download_token("abc123", settings=settings, now=1_700_000_000)
    tampered = f"{token}x"

    with pytest.raises(TokenError):
        parse_download_token(token=tampered, settings=settings, now=1_700_000_010)


def test_parse_download_token_rejects_expired_token() -> None:
    settings = _settings()
    token = create_download_token("abc123", settings=settings, now=1_700_000_000)

    with pytest.raises(TokenError):
        parse_download_token(token=token, settings=settings, now=1_700_000_070)
