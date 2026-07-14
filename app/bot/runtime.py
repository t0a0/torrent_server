"""Shared runtime state bridging the bot loop and the admin web thread.

The admin page (Phase C) runs in a daemon thread inside the bot process. It needs two
things from the asyncio side: the current connection status (to display), and a way to
force an immediate reconnect after the proxy list changes (instead of waiting up to the
retry interval). Both are mediated here so neither side reaches into the other directly.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field


@dataclass
class ConnectionStatus:
    """A snapshot of the bot's Telegram connection, safe to read from any thread."""

    state: str = "starting"  # "starting" | "connected" | "failed"
    proxy_description: str = "(none)"
    last_error: str | None = None
    updated_at: float = field(default_factory=time.time)


class BotRuntime:
    """Holds the live client/loop and connection status for cross-thread access."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._client = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._status = ConnectionStatus()

    def bind(self, client, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._client = client
            self._loop = loop

    def mark_connected(self, proxy_description: str) -> None:
        with self._lock:
            self._status = ConnectionStatus(
                state="connected", proxy_description=proxy_description
            )

    def mark_failed(self, proxy_description: str, error: str) -> None:
        with self._lock:
            self._status = ConnectionStatus(
                state="failed", proxy_description=proxy_description, last_error=error
            )

    def get_status(self) -> ConnectionStatus:
        with self._lock:
            return self._status

    def request_reconnect(self) -> bool:
        """Ask the running client to disconnect so the retry loop reconnects at once.

        Called from the web thread. Returns True if a reconnect was scheduled. Uses the
        same cross-thread bridge (``run_coroutine_threadsafe``) as completion
        notifications, so it is safe to call while the event loop runs elsewhere.
        """
        with self._lock:
            client = self._client
            loop = self._loop
        if client is None or loop is None:
            return False
        asyncio.run_coroutine_threadsafe(client.disconnect(), loop)
        return True


runtime = BotRuntime()
