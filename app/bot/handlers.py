"""Phase 1 bot command handlers."""

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from .auth import AuthService
from .config import get_owner_user_id

router = Router(name="phase1_handlers")
auth_service = AuthService(owner_user_id=get_owner_user_id())


def _escape_markdown_v2(value: str) -> str:
    escape_chars = r"_[]()~`>#+-=|{}.!"
    return "".join(f"\\{char}" if char in escape_chars else char for char in value)


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
    if await _require_whitelisted(message) is None:
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

    token = (command.args or "").strip()
    if not token:
        await message.answer("Usage: /authenticate <token>")
        return

    user_id, username = actor
    if auth_service.authenticate_user(token=token, user_id=user_id, username=username):
        await message.answer("Authentication successful. You are now whitelisted.")
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
        if user.username_at_authentication:
            escaped_username = _escape_markdown_v2(user.username_at_authentication)
            username_display = (
                f"[@{escaped_username}](https://t.me/{user.username_at_authentication})"
            )
        else:
            username_display = "N/A"

        lines.append(
            f"- user_id=`{user.user_id}`, "
            f"username_at_authentication={username_display}"
        )

    await message.answer("\n".join(lines), parse_mode="MarkdownV2")
