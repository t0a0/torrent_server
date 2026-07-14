"""Standalone Telegram connectivity checker.

Connects to Telegram with a proxy (the active one from the store, or one passed on the
command line), reports the detected secret type and connection class, and calls
``get_me()``. This is the way to test a proxy **from the deployment server** without
booting the whole stack, and it is the primary debugging tool for the FakeTLS path.

Usage:
    python -m app.tools.check_telegram [proxy]

``proxy`` may be a tg://proxy link, a socks5:// URL, host:port:secret, or ``direct``.
With no argument, the active proxy from the store is used. Exits non-zero on failure.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from telethon import TelegramClient

from app.bot.config import (
    get_api_hash,
    get_api_id,
    get_bot_token,
    get_mtproxy_seed,
    get_proxy_store_path,
    get_session_path,
)
from app.bot.mtproxy import Proxy, ProxyError, build_connection_kwargs, parse_proxy
from app.bot.proxy_store import ProxyStore


def _resolve_proxy(raw: str | None) -> Proxy:
    if raw is not None:
        return parse_proxy(raw)
    store = ProxyStore(get_proxy_store_path(), seed=get_mtproxy_seed())
    return store.get_active()


async def _check(proxy: Proxy) -> int:
    print(f"Proxy: {proxy.describe()}")
    kwargs = build_connection_kwargs(proxy)
    connection = kwargs.get("connection")
    if connection is not None:
        print(f"Connection class: {connection.__name__}")
    else:
        print("Connection class: (Telethon default; no MTProxy)")

    # Use an in-memory-ish separate session so this check never disturbs the bot's
    # session file lock while the bot may be running.
    client = TelegramClient(get_session_path() + ".check", get_api_id(), get_api_hash(), **kwargs)
    try:
        await client.start(bot_token=get_bot_token())
        me = await client.get_me()
        username = getattr(me, "username", None)
        print(f"OK: connected as @{username} (id={me.id})")
        return 0
    except Exception as exc:  # noqa: BLE001 - diagnostic tool reports any failure
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        await client.disconnect()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.tools.check_telegram",
        description="Check Telegram reachability through a proxy.",
    )
    parser.add_argument(
        "proxy",
        nargs="?",
        default=None,
        help="Proxy string (tg://, socks5://, host:port:secret, or 'direct'). "
        "Defaults to the active proxy in the store.",
    )
    args = parser.parse_args(argv)

    try:
        proxy = _resolve_proxy(args.proxy)
    except ProxyError as exc:
        print(f"Invalid proxy: {exc}", file=sys.stderr)
        return 2

    return asyncio.run(_check(proxy))


if __name__ == "__main__":
    raise SystemExit(main())
