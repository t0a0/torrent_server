"""Bot initialization utilities."""

from aiogram import Bot

from .config import get_bot_token


def create_bot() -> Bot:
    """Create an aiogram Bot instance using token from .env/env vars."""
    return Bot(token=get_bot_token())
