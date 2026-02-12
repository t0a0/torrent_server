"""Telegram command handlers scaffold."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="bot_handlers")


@router.message(Command("start"))
async def start_handler(message: Message) -> None:
    """Basic health-style start command for allowed users."""
    await message.answer("Torrent server bot is online.")
