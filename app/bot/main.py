"""Executable entrypoint for running the Telegram bot via long polling."""

import asyncio

from aiogram import Dispatcher

from .bot import create_bot
from .commands import setup_bot_commands
from .config import get_owner_user_id
from .integration import include_handlers


def create_dispatcher() -> Dispatcher:
    """Create dispatcher and register all bot handlers."""
    dispatcher = Dispatcher()
    include_handlers(dispatcher)
    return dispatcher


async def run_bot() -> None:
    """Initialize and start the bot polling loop."""
    bot = create_bot()
    await setup_bot_commands(bot=bot, owner_user_id=get_owner_user_id())
    dispatcher = create_dispatcher()
    await dispatcher.start_polling(bot)


def main() -> None:
    """Run bot in a dedicated asyncio event loop."""
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
