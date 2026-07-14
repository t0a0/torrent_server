"""Executable entrypoint for running the Telegram bot over MTProto (Telethon).

The retry loop is the graceful-degradation mechanism for the deployment reality that
Telegram is periodically blocked at the network edge in this server's region. On every
connection failure it rotates to the next proxy in the store and retries; the
background download workers (started at import of ``handlers``) only talk to
qBittorrent, so they keep running the whole time.
"""

import asyncio
import logging

from .bot import create_client
from .commands import setup_bot_commands
from .config import (
    get_admin_web_credentials,
    get_admin_web_port,
    get_bot_token,
    get_mtproxy_seed,
    get_owner_user_id,
    get_proxy_store_path,
)
from .handlers import bind_runtime_client, install_handlers
from .proxy_store import ProxyStore
from .runtime import runtime

logger = logging.getLogger(__name__)

# How long to wait before retrying when Telegram is unreachable (e.g. the active proxy
# is blocked). Each retry advances to the next proxy in the store.
_TELEGRAM_RETRY_SECONDS = 30.0


async def run_bot() -> None:
    """Run the connect/serve loop, rotating proxies and retrying on failure."""
    proxy_store = ProxyStore(get_proxy_store_path(), seed=get_mtproxy_seed())
    _maybe_start_admin_web(proxy_store)

    loop = asyncio.get_running_loop()

    while True:
        proxy = proxy_store.get_active()
        client = create_client(proxy)
        try:
            install_handlers(client)
            bind_runtime_client(client)
            runtime.bind(client, loop)

            await client.start(bot_token=get_bot_token())
            await setup_bot_commands(client=client, owner_user_id=get_owner_user_id())
            runtime.mark_connected(proxy.describe())
            logger.info("Connected to Telegram via %s", proxy.describe())

            await client.run_until_disconnected()
            # A clean disconnect (e.g. admin-triggered reconnect) falls through to
            # retry immediately with the (possibly updated) active proxy.
            logger.info("Telegram connection closed; reconnecting")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            runtime.mark_failed(proxy.describe(), str(exc))
            next_proxy = proxy_store.rotate()
            logger.exception(
                "Telegram unreachable via %s; rotating to %s, retry in %.0fs. "
                "Background download processing continues.",
                proxy.describe(),
                next_proxy.describe(),
                _TELEGRAM_RETRY_SECONDS,
            )
            await asyncio.sleep(_TELEGRAM_RETRY_SECONDS)
        finally:
            try:
                await client.disconnect()
            except Exception:
                logger.debug("Error while disconnecting client", exc_info=True)


def _maybe_start_admin_web(proxy_store: ProxyStore) -> None:
    """Start the proxy admin page if credentials are configured; otherwise skip it."""
    try:
        credentials = get_admin_web_credentials()
    except ValueError:
        logger.exception("Admin web page misconfigured; not starting it")
        return
    if credentials is None:
        logger.info("Admin web page disabled (ADMIN_WEB_USERNAME/PASSWORD not set)")
        return

    # Imported lazily so the bot runs even if the admin module is absent.
    from .admin_web import start_admin_web

    username, password = credentials
    start_admin_web(
        proxy_store=proxy_store,
        username=username,
        password=password,
        port=get_admin_web_port(),
    )


def main() -> None:
    """Run bot in a dedicated asyncio event loop."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
