"""Bot package with aiogram integration and command handlers."""

from .bot import create_bot
from .handlers import router
from .main import create_dispatcher, run_bot

__all__ = ["create_bot", "create_dispatcher", "router", "run_bot"]
