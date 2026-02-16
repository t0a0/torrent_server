"""Bot command handlers with auth and /add torrent integration."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from html import escape
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from app.download_links import DownloadLinkService
from app.torrent import (
    TorrentService,
    TorrentServiceError,
    ValidationError,
    validate_magnet_url,
    validate_torrent_file,
)
from app.torrent.policy import (
    get_add_rate_limit_per_minute,
    get_max_torrent_bytes_warn,
    get_torrent_input_tmp_dir,
)

from .auth import AuthService
from .commands import setup_non_whitelisted_commands, setup_whitelisted_commands
from .config import get_auth_db_path, get_owner_user_id

router = Router(name="phase3_handlers")
auth_service = AuthService(
    owner_user_id=get_owner_user_id(),
    db_path=get_auth_db_path(),
)
logger = logging.getLogger(__name__)


class AddFlowState(StatesGroup):
    waiting_for_torrent_input = State()


class AddRateLimiter:
    def __init__(self, max_per_minute: int) -> None:
        self._max_per_minute = max_per_minute
        self._events: dict[int, deque[float]] = defaultdict(deque)

    def allow(self, user_id: int) -> bool:
        now = monotonic()
        bucket = self._events[user_id]
        while bucket and (now - bucket[0]) >= 60:
            bucket.popleft()
        if len(bucket) >= self._max_per_minute:
            return False
        bucket.append(now)
        return True


@dataclass(slots=True)
class AddMetrics:
    counters: Counter[str]

    def inc(self, key: str) -> None:
        self.counters[key] += 1


add_metrics = AddMetrics(counters=Counter())
add_rate_limiter = AddRateLimiter(max_per_minute=get_add_rate_limit_per_minute())


def _build_download_link_service() -> DownloadLinkService | None:
    try:
        return DownloadLinkService()
    except ValueError:
        return None


def _build_torrent_service() -> TorrentService | None:
    try:
        return TorrentService()
    except Exception:
        logger.exception("Failed to initialize TorrentService")
        return None


download_link_service = _build_download_link_service()
torrent_service = _build_torrent_service()


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


def _map_qbit_error(exc: Exception) -> str:
    error_text = str(exc).lower()
    if "duplicate" in error_text or "already" in error_text:
        return "This torrent is already queued."
    if "connect" in error_text or "timeout" in error_text:
        return "Torrent service is temporarily unavailable. Please retry in a moment."
    return "Could not queue torrent in qBittorrent. Please try again later."


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
async def handle_add(message: Message, state: FSMContext) -> None:
    actor = await _require_whitelisted(message)
    if actor is None:
        return

    user_id, _ = actor
    if not add_rate_limiter.allow(user_id):
        add_metrics.inc("rejected_rate_limited")
        await message.answer("Rate limit exceeded. Please wait before adding more torrents.")
        return

    await state.set_state(AddFlowState.waiting_for_torrent_input)
    await message.answer("Paste a magnet URL or upload a .torrent file.")


@router.message(AddFlowState.waiting_for_torrent_input, Command("cancel"))
async def cancel_add_flow(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Add flow cancelled.")


@router.message(AddFlowState.waiting_for_torrent_input, F.document)
async def handle_add_uploaded_torrent(message: Message, state: FSMContext) -> None:
    actor = await _require_whitelisted(message)
    if actor is None:
        return
    user_id, _ = actor

    if torrent_service is None:
        add_metrics.inc("rejected_qbit_unavailable")
        await message.answer("Torrent service is unavailable. Please ask admin to check qBittorrent.")
        return

    document = message.document
    if document is None:
        add_metrics.inc("rejected_missing_document")
        await message.answer("Please upload a torrent file document.")
        return

    if not (document.file_name or "").lower().endswith(".torrent"):
        add_metrics.inc("rejected_extension")
        await message.answer("Please upload a .torrent file.")
        return

    tmp_dir = get_torrent_input_tmp_dir()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_file_path: Path | None = None
    infohash: str | None = None
    reason = "rejected_unknown"

    try:
        with NamedTemporaryFile(prefix="tg_", suffix=".torrent", dir=tmp_dir, delete=False) as tmp_file:
            tmp_file_path = Path(tmp_file.name)

        file_info = await message.bot.get_file(document.file_id)
        await message.bot.download_file(file_info.file_path, destination=tmp_file_path)

        result = validate_torrent_file(tmp_file_path)
        infohash = result.infohash

        if result.size_bytes > get_max_torrent_bytes_warn():
            logger.warning(
                "Large .torrent accepted user_id=%s size=%s infohash=%s",
                user_id,
                result.size_bytes,
                infohash,
            )

        if torrent_service.has_infohash(infohash):
            reason = "rejected_duplicate"
            add_metrics.inc(reason)
            await message.answer("This torrent is already queued or completed.")
            return

        torrent_service.start_download_from_file_bytes(user_id=user_id, torrent_file_bytes=tmp_file_path.read_bytes())
        add_metrics.inc("accepted_torrent_file")
        reason = "accepted"
        await state.clear()
        await message.answer("Torrent file accepted and queued for download.")
    except ValidationError as exc:
        reason = exc.reason_code
        add_metrics.inc(f"rejected_{exc.reason_code}")
        await message.answer(exc.user_message)
    except (TorrentServiceError, Exception) as exc:  # keep final branch user-safe
        reason = "qbit_error"
        add_metrics.inc("rejected_qbit_error")
        await message.answer(_map_qbit_error(exc))
        logger.exception("Failed to queue torrent file user_id=%s", user_id)
    finally:
        if tmp_file_path is not None and tmp_file_path.exists():
            tmp_file_path.unlink(missing_ok=True)
        logger.info(
            "add_torrent_file_decision user_id=%s size=%s infohash=%s reason=%s",
            user_id,
            document.file_size,
            infohash,
            reason,
        )


@router.message(AddFlowState.waiting_for_torrent_input, F.text)
async def handle_add_magnet(message: Message, state: FSMContext) -> None:
    actor = await _require_whitelisted(message)
    if actor is None:
        return

    user_id, _ = actor
    text = (message.text or "").strip()
    if not text:
        await message.answer("Paste a magnet URL or upload a .torrent file.")
        return

    if torrent_service is None:
        add_metrics.inc("rejected_qbit_unavailable")
        await message.answer("Torrent service is unavailable. Please ask admin to check qBittorrent.")
        return

    reason = "rejected_unknown"
    infohash: str | None = None
    started_at = monotonic()

    try:
        result = validate_magnet_url(text)
        infohash = result.infohash

        if torrent_service.has_infohash(result.infohash):
            reason = "rejected_duplicate"
            add_metrics.inc(reason)
            await message.answer("This torrent is already queued or completed.")
            return

        torrent_service.start_download_from_magnet_url(user_id=user_id, magnet_url=result.normalized_magnet)
        add_metrics.inc("accepted_magnet")
        reason = "accepted"
        await state.clear()
        await message.answer("Magnet link accepted and queued for download.")
    except ValidationError as exc:
        reason = exc.reason_code
        add_metrics.inc(f"rejected_{exc.reason_code}")
        await message.answer(exc.user_message)
    except (TorrentServiceError, Exception) as exc:
        reason = "qbit_error"
        add_metrics.inc("rejected_qbit_error")
        await message.answer(_map_qbit_error(exc))
        logger.exception("Failed to queue magnet user_id=%s", user_id)
    finally:
        latency_ms = int((monotonic() - started_at) * 1000)
        logger.info(
            "add_magnet_decision user_id=%s infohash=%s reason=%s latency_ms=%s",
            user_id,
            infohash,
            reason,
            latency_ms,
        )


@router.message(AddFlowState.waiting_for_torrent_input)
async def handle_add_unknown_input(message: Message) -> None:
    await message.answer("Unsupported input. Paste a magnet URL or upload a .torrent file.")


@router.message(Command("myfolder"))
async def handle_myfolder(message: Message) -> None:
    actor = await _require_whitelisted(message)
    if actor is None:
        return

    if download_link_service is None or not download_link_service.is_configured():
        await message.answer(
            "Folder links are not configured yet. Please ask admin to configure HFS_BASE_URL "
            "and DOWNLOAD_LINK_SECRET."
        )
        return

    user_id, _ = actor
    folder_link = download_link_service.build_user_folder_link(user_id=user_id)
    await message.answer(
        "Your personal download folder link (expires automatically):\n"
        f"{folder_link}\n\n"
        "This link is scoped to your Telegram user folder only."
    )


@router.message(Command("generateaccesstoken"))
async def handle_generate_access_token(message: Message) -> None:
    if await _require_admin(message) is None:
        return

    token = auth_service.generate_access_token()
    await message.answer(
        "Here is your access token command. Click the code below to copy it, "
        "then paste and send it to the bot.\n"
        "Valid for 30 minutes and single-use:\n"
        f"`/authenticate {token}`",
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
                    f"- user_id: <code>{user_id}</code>\n"
                    f"- username: {escape(username_display)}"
                ),
                parse_mode="HTML",
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
