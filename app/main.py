"""Application entrypoint scaffold."""

from __future__ import annotations

from aiogram import Bot, Dispatcher

from app.bot.handlers import router
from app.bot.middleware import AllowlistMiddleware
from app.config import Settings, load_settings
from app.services.qbittorrent_client import QBittorrentClient


def create_qbittorrent_client(settings: Settings) -> QBittorrentClient:
    """Create and authenticate a qBittorrent API client from env config."""
    client = QBittorrentClient(settings)
    client.login()
    return client


def create_dispatcher(settings: Settings) -> Dispatcher:
    """Create bot dispatcher and attach authorization middleware/routes."""
    dispatcher = Dispatcher()
    dispatcher.message.middleware(AllowlistMiddleware(settings))
    dispatcher.include_router(router)
    return dispatcher


def create_bot(settings: Settings) -> Bot:
    """Create aiogram bot instance from configured token."""
    return Bot(token=settings.telegram_bot_token)


if __name__ == "__main__":
    settings = load_settings()
    create_qbittorrent_client(settings)
    create_dispatcher(settings)
    create_bot(settings)
    print("Security baseline initialized (allowlist + signed token support).")
