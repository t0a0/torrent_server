"""Telegram command menu configuration utilities."""

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

USER_COMMANDS = [
    BotCommand(command="start", description="Start bot"),
    BotCommand(command="add", description="Add torrent or magnet"),
    BotCommand(command="authenticate", description="Authenticate with token"),
]

ADMIN_COMMANDS = [
    BotCommand(command="generateaccesstoken", description="Generate access token"),
    BotCommand(command="removeuser", description="Remove user from whitelist"),
    BotCommand(command="whitelist", description="Show whitelisted users"),
]


async def setup_bot_commands(bot: Bot, owner_user_id: int | None) -> None:
    """Apply command menus for default users and owner admin scope."""
    await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeDefault())

    if owner_user_id is None:
        return

    owner_commands = USER_COMMANDS + ADMIN_COMMANDS
    await bot.set_my_commands(
        owner_commands,
        scope=BotCommandScopeChat(chat_id=owner_user_id),
    )
