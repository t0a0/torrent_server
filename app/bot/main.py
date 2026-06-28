"""Executable entrypoint for running the Telegram bot via long polling."""

import asyncio
import logging

from aiogram import Dispatcher

from .bot import create_bot
from .commands import setup_bot_commands
from .config import get_owner_user_id
from .integration import include_handlers
from .handlers import bind_runtime_bot

logger = logging.getLogger(__name__)

# How long to wait before retrying Telegram setup/polling when it is unreachable
# (e.g. blocked at the network edge). The background download workers, which only
# talk to qBittorrent locally, keep running while we retry.
_TELEGRAM_RETRY_SECONDS = 30.0


def create_dispatcher() -> Dispatcher:
    """Create dispatcher and register all bot handlers."""
    dispatcher = Dispatcher()
    include_handlers(dispatcher)
    return dispatcher


async def run_bot() -> None:
    """Run the bot polling loop, retrying if Telegram is unreachable.

    Importing the handlers module already started the background download workers
    (move-to-finished and retention). Those depend only on qBittorrent, not Telegram,
    so this loop must keep the main thread alive even when Telegram cannot be reached:
    otherwise a restart while Telegram is blocked would crash the process and take the
    download workers down with it.
    """
    bot = create_bot()
    bind_runtime_bot(bot)
    dispatcher = create_dispatcher()

    while True:
        try:
            await setup_bot_commands(bot=bot, owner_user_id=get_owner_user_id())
            await dispatcher.start_polling(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Telegram is unreachable (it may be blocked); retrying in %.0f seconds. "
                "Background download processing continues.",
                _TELEGRAM_RETRY_SECONDS,
            )
            await asyncio.sleep(_TELEGRAM_RETRY_SECONDS)


def main() -> None:
    """Run bot in a dedicated asyncio event loop."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
