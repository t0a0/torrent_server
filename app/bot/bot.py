"""Bot initialization utilities."""

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from .config import get_bot_token, get_telegram_proxy


def create_bot() -> Bot:
    """Create an aiogram Bot instance using token from .env/env vars.

    When ``TELEGRAM_PROXY`` is set, the bot reaches the Bot API through that proxy
    (e.g. a SOCKS5 tunnel) so it can connect where Telegram is blocked. A SOCKS5 proxy
    forwards the ordinary HTTPS Bot API traffic, so no protocol change is needed.
    """
    proxy = get_telegram_proxy()
    session = AiohttpSession(proxy=proxy) if proxy else None
    return Bot(token=get_bot_token(), session=session)
