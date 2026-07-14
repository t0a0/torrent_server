"""A tiny first-match-wins router over Telethon events.

aiogram and Telethon dispatch in opposite ways. aiogram tries handlers in
registration order and stops at the **first** match; Telethon runs **every** matching
handler unless one raises ``events.StopPropagation``. A naive port of the handlers
would therefore fire the bare catch-all on ``/start``, ``/status`` and every other
command in addition to the real handler.

This router restores aiogram's semantics with a single ``NewMessage`` handler and a
single ``CallbackQuery`` handler that each dispatch internally to the first matching
entry. New handlers get correct behaviour for free — there are no per-handler
``StopPropagation`` calls to remember.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from telethon import TelegramClient, events

logger = logging.getLogger(__name__)

MessageHandler = Callable[[events.NewMessage.Event], Awaitable[None]]
CallbackHandler = Callable[[events.CallbackQuery.Event], Awaitable[None]]


def command_name(raw_text: str | None) -> str | None:
    """Return the lowercased command name of a ``/command`` message, else ``None``.

    Handles the ``/name@botusername`` form Telegram uses in groups, and arguments
    (``/name arg1 arg2``). Non-command text (including empty document captions) yields
    ``None`` so it flows to the fallback handler.
    """
    if not raw_text:
        return None
    text = raw_text.strip()
    if not text.startswith("/"):
        return None
    first = text[1:].split(maxsplit=1)[0]
    name = first.split("@", maxsplit=1)[0]
    return name.lower() or None


def command_args(raw_text: str | None) -> str:
    """Return the argument string after a ``/command`` (the aiogram ``CommandObject.args``)."""
    if not raw_text:
        return ""
    text = raw_text.strip()
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else ""


class Router:
    """Collects handlers; :func:`install` wires them onto a client."""

    def __init__(self) -> None:
        self._commands: list[tuple[str, MessageHandler]] = []
        self._callbacks: list[tuple[bytes, CallbackHandler]] = []
        self._fallback: MessageHandler | None = None

    def command(self, name: str) -> Callable[[MessageHandler], MessageHandler]:
        """Register a handler for ``/name`` (first registration wins on match)."""

        def decorator(func: MessageHandler) -> MessageHandler:
            self._commands.append((name.lower(), func))
            return func

        return decorator

    def callback(self, prefix: str) -> Callable[[CallbackHandler], CallbackHandler]:
        """Register a handler for callback data starting with ``prefix``."""

        def decorator(func: CallbackHandler) -> CallbackHandler:
            self._callbacks.append((prefix.encode(), func))
            return func

        return decorator

    def fallback(self) -> Callable[[MessageHandler], MessageHandler]:
        """Register the single catch-all for non-command messages."""

        def decorator(func: MessageHandler) -> MessageHandler:
            if self._fallback is not None:
                raise RuntimeError("Only one fallback handler may be registered")
            self._fallback = func
            return func

        return decorator

    def install(self, client: TelegramClient) -> None:
        """Attach exactly one message and one callback dispatcher to the client."""

        @client.on(events.NewMessage(incoming=True))
        async def _on_message(event: events.NewMessage.Event) -> None:
            name = command_name(event.raw_text)
            if name is not None:
                for cmd_name, handler in self._commands:
                    if cmd_name == name:
                        await handler(event)
                        return
                # Unknown command: fall through to the fallback, which ignores it
                # unless the user is mid-flow (matching the old aiogram behaviour).
            if self._fallback is not None:
                await self._fallback(event)

        @client.on(events.CallbackQuery())
        async def _on_callback(event: events.CallbackQuery.Event) -> None:
            data = event.data or b""
            for prefix, handler in self._callbacks:
                if data.startswith(prefix):
                    await handler(event)
                    return
            logger.debug("Unhandled callback data: %r", data)
