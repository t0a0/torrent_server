"""Application entrypoint scaffold."""

from __future__ import annotations

from aiogram import Bot, Dispatcher

from app.bot.handlers import create_router
from app.config import Settings, load_settings
from app.services.qbittorrent_client import QBittorrentClient


def create_qbittorrent_client(settings: Settings) -> QBittorrentClient:
    """Create and authenticate a qBittorrent API client from env config."""
    client = QBittorrentClient(settings)
    client.login()
    return client


def create_dispatcher(settings: Settings) -> Dispatcher:
    """Create bot dispatcher and register allowlist-enforced handlers."""
    dispatcher = Dispatcher()
    dispatcher.include_router(create_router(settings.telegram_allowed_user_ids))
    return dispatcher


def bootstrap() -> tuple[Settings, Bot, Dispatcher, QBittorrentClient]:
    """Initialize major runtime components without starting polling."""
    settings = load_settings()
    bot = Bot(token=settings.telegram_bot_token)
    dispatcher = create_dispatcher(settings)
    qb_client = create_qbittorrent_client(settings)
    return settings, bot, dispatcher, qb_client


if __name__ == "__main__":
    bootstrap()
    print("Runtime components initialized successfully.")
