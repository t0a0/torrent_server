from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.config import Settings
from app.services.qbittorrent_client import QBittorrentClient


@dataclass
class DummyTorrent:
    hash: str
    name: str
    state: str
    progress: float


class DummyClient:
    def __init__(self) -> None:
        self.logged_in = False
        self.added_urls: list[str] = []

    def auth_log_in(self) -> None:
        self.logged_in = True

    def torrents_add(self, urls: str) -> None:
        self.added_urls.append(urls)

    def torrents_info(self) -> list[DummyTorrent]:
        return [DummyTorrent(hash="abc", name="ubuntu.iso", state="downloading", progress=0.42)]


@pytest.fixture
def settings() -> Settings:
    return Settings(
        telegram_bot_token="token",
        telegram_allowed_user_ids=frozenset({1}),
        qbittorrent_base_url="http://qbittorrent:8080",
        qbittorrent_username="admin",
        qbittorrent_password="password",
        qbittorrent_verify_certificate=False,
        sqlite_path="./data/db.sqlite3",
        download_base_url="https://downloads.example.com",
        download_token_secret="secret",
        download_token_ttl_seconds=3600,
    )


def test_qbittorrent_wrapper(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(
        "app.services.qbittorrent_client._create_api_client",
        lambda _: DummyClient(),
    )

    client = QBittorrentClient(settings)
    client.login()
    client.add_magnet("magnet:?xt=urn:btih:test")
    torrents = client.list_torrents()

    assert torrents[0].name == "ubuntu.iso"
    assert torrents[0].progress == 0.42
