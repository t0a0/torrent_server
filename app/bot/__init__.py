"""Bot package with aiogram integration and command handlers."""

from .bot import create_bot
from .handlers import router

__all__ = ["create_bot", "router"]
