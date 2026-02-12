"""Bot middleware for request authorization."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message

from app.config import Settings
from app.security.auth import extract_message_user_id, is_allowed_telegram_user


class AllowlistMiddleware(BaseMiddleware):
    """Reject commands from Telegram users outside configured allowlist."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        user_id = extract_message_user_id(event)
        if user_id is None or not is_allowed_telegram_user(user_id, self._settings):
            await event.answer("Unauthorized: your Telegram user ID is not allowed.")
            return None
        return await handler(event, data)
