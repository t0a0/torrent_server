"""aiogram middleware for Telegram allowlist enforcement."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, User

from app.security.auth import is_user_allowed

UNAUTHORIZED_MESSAGE = "Unauthorized: this bot is restricted to approved users."


class AllowlistMiddleware(BaseMiddleware):
    """Block incoming Telegram events from users outside the configured allowlist."""

    def __init__(self, allowed_user_ids: frozenset[int]) -> None:
        self._allowed_user_ids = allowed_user_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable[object]],
        event: TelegramObject,
        data: dict,
    ) -> object:
        user = data.get("event_from_user")
        if not isinstance(user, User):
            return await handler(event, data)

        if not is_user_allowed(user.id, self._allowed_user_ids):
            message = event if isinstance(event, Message) else None
            if message is not None:
                await message.answer(UNAUTHORIZED_MESSAGE)
            return None

        return await handler(event, data)
