"""Telegram command menu configuration (Telethon / raw MTProto).

Telethon has no high-level ``set_my_commands`` with per-chat scopes, so we call the
raw ``bots.setBotCommands`` request directly. The command lists and the scoping
behaviour are unchanged from before: non-whitelisted users see ``/start`` +
``/authenticate``; whitelisted users see the download commands; the owner also sees
the admin commands.
"""

from __future__ import annotations

import logging

from telethon import TelegramClient
from telethon.errors import RPCError
from telethon.tl.functions.bots import SetBotCommandsRequest
from telethon.tl.types import BotCommand, BotCommandScopeDefault, BotCommandScopePeer

logger = logging.getLogger(__name__)

NON_WHITELISTED_COMMANDS = [
    BotCommand(command="start", description="Start bot"),
    BotCommand(command="authenticate", description="Authenticate with token"),
]

WHITELISTED_COMMANDS = [
    BotCommand(command="start", description="Start bot"),
    BotCommand(command="queuedownload", description="Queue torrent or magnet"),
    BotCommand(command="getdownloadlink", description="Get link for finished download"),
    BotCommand(command="deletefiles", description="Delete finished downloads"),
    BotCommand(command="cancel", description="Cancel pending command input"),
    BotCommand(command="status", description="Show current torrent progress"),
    BotCommand(command="canceldownload", description="Cancel and delete active download"),
    BotCommand(command="myfolder", description="Get private download folder link"),
]

ADMIN_COMMANDS = [
    BotCommand(command="generateaccesstoken", description="Generate access token"),
    BotCommand(command="removeuser", description="Remove user from whitelist"),
    BotCommand(command="whitelist", description="Show whitelisted users"),
    BotCommand(command="availablespace", description="Show available disk space"),
]


async def _set_commands(client: TelegramClient, commands: list[BotCommand], scope) -> None:
    await client(SetBotCommandsRequest(scope=scope, lang_code="", commands=commands))


async def _set_commands_for_user(client: TelegramClient, user_id: int, commands: list[BotCommand]) -> None:
    """Apply a command menu scoped to one user chat.

    Resolving the peer requires the bot to have seen the user. That holds for callers
    that just messaged the bot, but ``/removeuser`` targets an arbitrary user_id, so
    failures are logged rather than allowed to kill the handler.
    """
    try:
        peer = await client.get_input_entity(user_id)
    except (ValueError, RPCError):
        logger.warning("Cannot scope commands for unknown user_id=%s", user_id)
        return
    await _set_commands(client, commands, BotCommandScopePeer(peer))


async def setup_bot_commands(client: TelegramClient, owner_user_id: int | None) -> None:
    """Apply command menus for default users and owner admin scope."""
    await _set_commands(client, NON_WHITELISTED_COMMANDS, BotCommandScopeDefault())

    if owner_user_id is None:
        return

    await setup_whitelisted_commands(client=client, user_id=owner_user_id, is_admin=True)


async def setup_non_whitelisted_commands(client: TelegramClient, user_id: int) -> None:
    """Apply command menu for a specific non-whitelisted user chat."""
    await _set_commands_for_user(client, user_id, NON_WHITELISTED_COMMANDS)


async def setup_whitelisted_commands(client: TelegramClient, user_id: int, is_admin: bool = False) -> None:
    """Apply command menu for a specific whitelisted (optionally admin) user chat."""
    commands = WHITELISTED_COMMANDS + ADMIN_COMMANDS if is_admin else WHITELISTED_COMMANDS
    await _set_commands_for_user(client, user_id, commands)
