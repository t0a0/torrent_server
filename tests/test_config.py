from __future__ import annotations

import os

import pytest

from app.config import ConfigError, load_settings


@pytest.fixture(autouse=True)
def reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith(("TELEGRAM_", "QBITTORRENT_", "DOWNLOAD_", "SQLITE_")):
            monkeypatch.delenv(key, raising=False)


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "1001,1002")
    monkeypatch.setenv("QBITTORRENT_BASE_URL", "http://qbittorrent:8080")
    monkeypatch.setenv("QBITTORRENT_USERNAME", "admin")
    monkeypatch.setenv("QBITTORRENT_PASSWORD", "secret")
    monkeypatch.setenv("DOWNLOAD_BASE_URL", "https://downloads.example.com")
    monkeypatch.setenv("DOWNLOAD_TOKEN_SECRET", "super-secret")


def test_load_settings_parses_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("QBITTORRENT_VERIFY_CERTIFICATE", "true")
    monkeypatch.setenv("DOWNLOAD_TOKEN_TTL_SECONDS", "7200")

    settings = load_settings()

    assert settings.telegram_allowed_user_ids == frozenset({1001, 1002})
    assert settings.qbittorrent_verify_certificate is True
    assert settings.download_token_ttl_seconds == 7200


def test_load_settings_requires_allowed_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "")

    with pytest.raises(ConfigError):
        load_settings()
