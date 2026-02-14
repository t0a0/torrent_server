"""Phase 1 bot command handlers."""

from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from .auth import AuthService
from .commands import setup_non_whitelisted_commands, setup_whitelisted_commands
from .config import get_owner_user_id

router = Router(name="phase1_handlers")
auth_service = AuthService(owner_user_id=get_owner_user_id())


def _get_actor(message: Message) -> tuple[int, str | None] | None:
    actor = message.from_user
    if actor is None:
        return None
    return actor.id, actor.username


async def _require_admin(message: Message) -> tuple[int, str | None] | None:
    actor = _get_actor(message)
    if actor is None:
        await message.answer("Cannot resolve caller identity.")
        return None

    user_id, _ = actor
    if not auth_service.is_admin(user_id=user_id):
        await message.answer("This command is admin-only.")
        return None
    return actor


async def _require_whitelisted(message: Message) -> tuple[int, str | None] | None:
    actor = _get_actor(message)
    if actor is None:
        await message.answer("Cannot resolve caller identity.")
        return None

    user_id, _ = actor
    if not auth_service.is_whitelisted(user_id):
        await message.answer("You are not authenticated. Use /authenticate <token>.")
        return None
    return actor


@router.message(Command("start"))
async def handle_start(message: Message) -> None:
    actor = _get_actor(message)
    if actor is None:
        await message.answer("Cannot resolve caller identity.")
        return

    user_id, _ = actor
    if not auth_service.is_whitelisted(user_id):
        await message.answer(
            "You are not whitelisted yet. Request an access token from the admin and "
            "use /authenticate <token> to get whitelisted before using the bot."
        )
        return

    await message.answer("Welcome! Use /add to submit a torrent or magnet link.")


@router.message(Command("add"))
async def handle_add(message: Message) -> None:
    if await _require_whitelisted(message) is None:
        return
    await message.answer("/add is acknowledged. Torrent integration is pending in Phase 2.")


@router.message(Command("generateaccesstoken"))
async def handle_generate_access_token(message: Message) -> None:
    if await _require_admin(message) is None:
        return

    token = auth_service.generate_access_token()
    await message.answer(
        "Access token (valid for 30 minutes, single-use):\n"
        f"`{token}`",
        parse_mode="Markdown",
    )


@router.message(Command("authenticate"))
async def handle_authenticate(message: Message, command: CommandObject) -> None:
    actor = _get_actor(message)
    if actor is None:
        await message.answer("Cannot resolve caller identity.")
        return

    user_id, username = actor
    if auth_service.is_whitelisted(user_id):
        await message.answer("You are already whitelisted. Auth token was not consumed.")
        return

    token = (command.args or "").strip()
    if not token:
        await message.answer("Usage: /authenticate <token>")
        return

    if auth_service.authenticate_user(token=token, user_id=user_id, username=username):
        await message.answer("Authentication successful. You are now whitelisted.")
        await setup_whitelisted_commands(
            bot=message.bot,
            user_id=user_id,
            is_admin=auth_service.is_admin(user_id=user_id),
        )
        owner_user_id = get_owner_user_id()
        if owner_user_id is not None:
            username_display = f"@{username}" if username else "<none>"
            await message.bot.send_message(
                chat_id=owner_user_id,
                text=(
                    "User authenticated successfully:\n"
                    f"- user_id: {user_id}\n"
                    f"- username: {username_display}"
                ),
            )
        return

    await message.answer("Invalid or expired token.")


@router.message(Command("removeuser"))
async def handle_removeuser(message: Message, command: CommandObject) -> None:
    if await _require_admin(message) is None:
        return

    raw_user_id = (command.args or "").strip()
    if not raw_user_id:
        await message.answer("Usage: /removeuser <user_id>")
        return

    try:
        target_user_id = int(raw_user_id)
    except ValueError:
        await message.answer("user_id must be an integer.")
        return

    if auth_service.remove_user(target_user_id):
        await setup_non_whitelisted_commands(bot=message.bot, user_id=target_user_id)
        await message.answer(f"Removed user {target_user_id} from whitelist.")
        return

    await message.answer(f"User {target_user_id} is not whitelisted.")


@router.message(Command("whitelist"))
async def handle_whitelist(message: Message) -> None:
    if await _require_admin(message) is None:
        return

    users = auth_service.list_whitelisted_users()
    if not users:
        await message.answer("Whitelist is empty.")
        return

    lines = ["Whitelisted users:"]
    for user in users:
        username = user.username_at_authentication
        username_display = f"@{username}" if username else "<none>"
        lines.append(
            f"- user_id=<code>{user.user_id}</code>, "
            f"username_at_authentication={escape(username_display)}"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")
