"""Telegram command menu configuration utilities."""

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

NON_WHITELISTED_COMMANDS = [
    BotCommand(command="start", description="Start bot"),
    BotCommand(command="authenticate", description="Authenticate with token"),
]

WHITELISTED_COMMANDS = [
    BotCommand(command="start", description="Start bot"),
    BotCommand(command="add", description="Add torrent or magnet"),
]

ADMIN_COMMANDS = [
    BotCommand(command="generateaccesstoken", description="Generate access token"),
    BotCommand(command="removeuser", description="Remove user from whitelist"),
    BotCommand(command="whitelist", description="Show whitelisted users"),
]


async def setup_bot_commands(bot: Bot, owner_user_id: int | None) -> None:
    """Apply command menus for default users and owner admin scope."""
    await bot.set_my_commands(NON_WHITELISTED_COMMANDS, scope=BotCommandScopeDefault())

    if owner_user_id is None:
        return

    await setup_whitelisted_commands(bot=bot, user_id=owner_user_id, is_admin=True)


async def setup_non_whitelisted_commands(bot: Bot, user_id: int) -> None:
    """Apply command menu for a specific non-whitelisted user chat."""
    await bot.set_my_commands(
        NON_WHITELISTED_COMMANDS,
        scope=BotCommandScopeChat(chat_id=user_id),
    )


async def setup_whitelisted_commands(bot: Bot, user_id: int, is_admin: bool = False) -> None:
    """Apply command menu for a specific whitelisted (optionally admin) user chat."""
    commands = WHITELISTED_COMMANDS + ADMIN_COMMANDS if is_admin else WHITELISTED_COMMANDS
    await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=user_id))
