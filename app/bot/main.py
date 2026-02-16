"""Executable entrypoint for running the Telegram bot via long polling."""

import asyncio
import logging

from aiogram import Dispatcher

from .bot import create_bot
from .commands import setup_bot_commands
from .config import get_owner_user_id
from .integration import include_handlers
from .handlers import bind_runtime_bot


def create_dispatcher() -> Dispatcher:
    """Create dispatcher and register all bot handlers."""
    dispatcher = Dispatcher()
    include_handlers(dispatcher)
    return dispatcher


async def run_bot() -> None:
    """Initialize and start the bot polling loop."""
    bot = create_bot()
    bind_runtime_bot(bot)
    await setup_bot_commands(bot=bot, owner_user_id=get_owner_user_id())
    dispatcher = create_dispatcher()
    await dispatcher.start_polling(bot)


def main() -> None:
    """Run bot in a dedicated asyncio event loop."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
