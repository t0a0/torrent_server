"""Telethon client construction."""

from __future__ import annotations

from telethon import TelegramClient

from .config import get_api_hash, get_api_id, get_session_path
from .mtproxy import Proxy, build_connection_kwargs


def create_client(proxy: Proxy | None) -> TelegramClient:
    """Create a TelegramClient for the given proxy (None/direct = no proxy).

    A fresh client is built per connection attempt so the failover loop in ``main``
    can try a different proxy each time simply by passing a different ``proxy`` here.
    The session file is shared across attempts, so the bot reuses its auth key rather
    than redoing the DH handshake on every reconnect.
    """
    return TelegramClient(
        get_session_path(),
        get_api_id(),
        get_api_hash(),
        **build_connection_kwargs(proxy),
    )
