"""Bot package with aiogram integration and command handlers."""

from .bot import create_bot
from .handlers import router

__all__ = ["create_bot", "create_dispatcher", "router", "run_bot"]


def create_dispatcher():
    """Create dispatcher and register all bot handlers."""
    from .main import create_dispatcher as _create_dispatcher

    return _create_dispatcher()


async def run_bot() -> None:
    """Initialize and start the bot polling loop."""
    from .main import run_bot as _run_bot

    await _run_bot()
