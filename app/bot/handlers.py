"""Telegram command handlers."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.middleware import AllowlistMiddleware


def create_router(allowed_user_ids: frozenset[int]) -> Router:
    """Build the Telegram router and attach runtime allowlist enforcement."""
    router = Router(name="bot_handlers")
    router.message.middleware(AllowlistMiddleware(allowed_user_ids=allowed_user_ids))

    @router.message(Command("start"))
    async def start_handler(message: Message) -> None:
        await message.answer("Torrent server bot is running.")

    @router.message(Command("status"))
    async def status_handler(message: Message) -> None:
        await message.answer("Queue/status handlers are not implemented yet.")

    return router
