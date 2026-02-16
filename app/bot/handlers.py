"""Phase 3 bot command handlers."""

from __future__ import annotations

import asyncio
from html import escape
import logging
import secrets
import time

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from .auth import AuthService
from .commands import setup_non_whitelisted_commands, setup_whitelisted_commands
from .config import get_auth_db_path, get_owner_user_id
from app.download_links import DownloadLinkService
from app.torrent import CompletedTorrent, TorrentService
from app.torrent.config import (
    get_queue_download_rate_limit_per_min,
    get_max_magnet_trackers,
    get_max_magnet_url_length,
    get_max_torrent_aggregate_size_bytes,
    get_max_torrent_bytes_hard,
    get_max_torrent_bytes_warn,
    get_max_torrent_file_count,
    get_max_torrent_name_length,
    get_max_torrent_path_segment_length,
    get_max_tracker_url_length,
    get_qbit_api_timeout_seconds,
    get_torrent_input_tmp_dir,
)
from app.torrent.policy import QueueDownloadPolicyService
from app.torrent.validators import ValidationError, validate_magnet_url, validate_torrent_file_bytes

router = Router(name="phase3_handlers")
logger = logging.getLogger(__name__)
auth_service = AuthService(
    owner_user_id=get_owner_user_id(),
    db_path=get_auth_db_path(),
)


class _QueueDownloadSessionState:
    def __init__(self) -> None:
        self._waiting_users: dict[int, str] = {}

    def begin_waiting(self, user_id: int, command: str) -> None:
        self._waiting_users[user_id] = command

    def is_waiting(self, user_id: int) -> bool:
        return user_id in self._waiting_users

    def get_waiting_command(self, user_id: int) -> str | None:
        return self._waiting_users.get(user_id)

    def clear_waiting(self, user_id: int) -> None:
        self._waiting_users.pop(user_id, None)


queue_download_session_state = _QueueDownloadSessionState()
queue_download_policy = QueueDownloadPolicyService(
    queue_downloads_per_minute=get_queue_download_rate_limit_per_min()
)


class _CompletionNotifier:
    def __init__(self) -> None:
        self._bot: Bot | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_runtime(self, bot: Bot) -> None:
        self._bot = bot
        self._loop = asyncio.get_running_loop()

    def on_torrent_completed(self, torrent: CompletedTorrent) -> None:
        if torrent.user_id is None:
            logger.warning("Cannot notify torrent completion without user_id hash=%s", torrent.hash)
            return

        if self._bot is None or self._loop is None:
            logger.warning("Bot runtime is not bound yet; skipping completion notification hash=%s", torrent.hash)
            return

        future = asyncio.run_coroutine_threadsafe(
            self._send_completion_message(torrent),
            self._loop,
        )

        def _handle_result(done_future: asyncio.Future[None]) -> None:
            try:
                done_future.result()
            except Exception:
                logger.exception("Failed to send completion notification hash=%s", torrent.hash)

        future.add_done_callback(_handle_result)

    async def _send_completion_message(self, torrent: CompletedTorrent) -> None:
        assert self._bot is not None
        assert torrent.user_id is not None

        torrent_name = escape((torrent.name or "(unnamed torrent)")[:96])
        text = f"✅ Download finished: <b>{torrent_name}</b>"
        if download_link_service is not None and download_link_service.is_configured():
            folder_link = download_link_service.build_user_folder_link(user_id=torrent.user_id)
            text = f"{text}\n\nYour download folder link:\n{folder_link}"

        await self._bot.send_message(
            chat_id=torrent.user_id,
            text=text,
            parse_mode="HTML",
        )


completion_notifier = _CompletionNotifier()


def _build_download_link_service() -> DownloadLinkService | None:
    try:
        return DownloadLinkService()
    except ValueError:
        return None


def _build_torrent_service() -> TorrentService | None:
    try:
        return TorrentService(on_torrent_completed=completion_notifier.on_torrent_completed)
    except ValueError:
        logger.exception("Failed to initialize TorrentService")
        return None


download_link_service = _build_download_link_service()
torrent_service = _build_torrent_service()


def bind_runtime_bot(bot: Bot) -> None:
    """Bind active bot/loop so background workers can send Telegram notifications."""
    completion_notifier.bind_runtime(bot)


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

    await message.answer("Welcome! Use /queuedownload to submit a torrent or magnet link.")


@router.message(Command("queuedownload"))
async def handle_queuedownload(message: Message) -> None:
    actor = await _require_whitelisted(message)
    if actor is None:
        return

    user_id, _ = actor
    if not queue_download_policy.enforce_rate_limit(user_id):
        await message.answer("Too many queue requests right now. Please wait a minute and try again.")
        return

    queue_download_session_state.begin_waiting(user_id=user_id, command="queuedownload")
    await message.answer("Paste a magnet URL or upload a .torrent file.")


@router.message(Command("cancel"))
async def handle_cancel(message: Message) -> None:
    actor = _get_actor(message)
    if actor is None:
        await message.answer("Cannot resolve caller identity.")
        return

    user_id, _ = actor
    waiting_command = queue_download_session_state.get_waiting_command(user_id)
    if waiting_command is None:
        await message.answer("There is no pending command input to cancel.")
        return

    queue_download_session_state.clear_waiting(user_id)
    await message.answer(f"Cancelled /{waiting_command} input.")


@router.message(Command("status"))
async def handle_status(message: Message) -> None:
    actor = await _require_whitelisted(message)
    if actor is None:
        return

    if torrent_service is None:
        await message.answer("Torrent service is currently unavailable. Please contact admin.")
        return

    user_id, _ = actor
    try:
        queued_torrents = await asyncio.wait_for(
            asyncio.to_thread(
                torrent_service.list_user_queued_torrents,
                user_id,
            ),
            timeout=get_qbit_api_timeout_seconds(),
        )
    except TimeoutError:
        await message.answer(_map_qbit_user_message("qbit_timeout"))
        return
    except Exception as exc:
        reason = _map_qbit_error(exc)
        await message.answer(_map_qbit_user_message(reason))
        return

    if not queued_torrents:
        await message.answer("You have no active queued torrents.")
        return

    lines = ["Your active torrents:"]
    for torrent in queued_torrents:
        torrent_name = escape(torrent.name[:64])
        torrent_state = escape(torrent.state or "unknown")
        lines.append(
            f"• {torrent_name} — State: <b>{torrent_state}</b> | Downloaded: <b>{torrent.progress_percent:.1f}%</b>"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


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


@router.message()
async def handle_queue_download_input(message: Message) -> None:
    actor = _get_actor(message)
    if actor is None:
        return

    user_id, _ = actor
    if not queue_download_session_state.is_waiting(user_id):
        return

    if not auth_service.is_whitelisted(user_id):
        queue_download_session_state.clear_waiting(user_id)
        await message.answer("You are not authenticated. Use /authenticate <token>.")
        return

    if torrent_service is None:
        queue_download_session_state.clear_waiting(user_id)
        await message.answer("Torrent service is currently unavailable. Please contact admin.")
        return

    if message.document is not None:
        await _process_queue_download_torrent_upload(message=message, user_id=user_id)
        return

    text = (message.text or "").strip()
    if text:
        await _process_queue_download_magnet_input(message=message, user_id=user_id, text=text)
        return

    await message.answer("Please paste a magnet URL or upload a .torrent file.")


async def _process_queue_download_torrent_upload(message: Message, user_id: int) -> None:
    assert message.document is not None
    document = message.document
    original_name = document.file_name or "upload.torrent"
    if not original_name.lower().endswith(".torrent"):
        await message.answer("Please upload a .torrent file.")
        queue_download_policy.mark_rejection("torrent_extension")
        return

    if document.file_size is not None and document.file_size > get_max_torrent_bytes_hard():
        await message.answer("Torrent file is too large.")
        queue_download_policy.mark_rejection("torrent_size_hard")
        logger.info("/queuedownload rejected upload user_id=%s reason=%s size=%s", user_id, "torrent_size_hard", document.file_size)
        return

    temp_input_dir = get_torrent_input_tmp_dir()
    temp_input_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_input_dir / f"{secrets.token_hex(16)}.torrent"
    infohash: str | None = None
    reason = "accepted"
    try:
        tg_file = await message.bot.get_file(document.file_id)
        await message.bot.download_file(tg_file.file_path, destination=temp_path)
        torrent_bytes = temp_path.read_bytes()

        if len(torrent_bytes) > get_max_torrent_bytes_hard():
            queue_download_policy.mark_rejection("torrent_size_hard")
            await message.answer("Torrent file is too large.")
            reason = "torrent_size_hard"
            return

        if len(torrent_bytes) > get_max_torrent_bytes_warn():
            logger.warning("/queuedownload large torrent metadata user_id=%s size=%s", user_id, len(torrent_bytes))

        validation = validate_torrent_file_bytes(
            torrent_bytes=torrent_bytes,
            max_torrent_name_length=get_max_torrent_name_length(),
            max_tracker_url_length=get_max_tracker_url_length(),
            max_path_segment_length=get_max_torrent_path_segment_length(),
            max_torrent_file_count=get_max_torrent_file_count(),
            max_torrent_aggregate_size_bytes=get_max_torrent_aggregate_size_bytes(),
        )
        infohash = validation.infohash

        started_at = time.monotonic()
        await asyncio.wait_for(
            asyncio.to_thread(
                torrent_service.start_download_from_file_bytes,
                user_id,
                torrent_bytes,
            ),
            timeout=get_qbit_api_timeout_seconds(),
        )
        queue_download_policy.mark_qbit_latency(time.monotonic() - started_at)
        queue_download_policy.mark_accepted()
        queue_download_session_state.clear_waiting(user_id)
        await message.answer("Torrent accepted and queued for download.")
    except ValidationError as exc:
        reason = exc.code
        queue_download_policy.mark_rejection(exc.code)
        await message.answer(exc.user_message)
    except TimeoutError:
        reason = "qbit_timeout"
        queue_download_policy.mark_qbit_error()
        await message.answer("Torrent service timed out while queueing this torrent. Please retry.")
    except Exception as exc:
        reason = _map_qbit_error(exc)
        queue_download_policy.mark_qbit_error()
        await message.answer(_map_qbit_user_message(reason))
    finally:
        logger.info(
            "/queuedownload torrent upload decision user_id=%s size=%s infohash=%s reason=%s",
            user_id,
            document.file_size,
            infohash,
            reason,
        )
        temp_path.unlink(missing_ok=True)


async def _process_queue_download_magnet_input(message: Message, user_id: int, text: str) -> None:
    infohash: str | None = None
    reason = "accepted"
    try:
        validation = validate_magnet_url(
            magnet_url=text,
            max_url_length=get_max_magnet_url_length(),
            max_trackers=get_max_magnet_trackers(),
            max_param_length=get_max_tracker_url_length(),
            require_source_param=True,
        )
        infohash = validation.infohash

        if torrent_service is None:
            reason = "service_unavailable"
            await message.answer("Torrent service is currently unavailable. Please contact admin.")
            return

        started_at = time.monotonic()
        await asyncio.wait_for(
            asyncio.to_thread(
                torrent_service.start_download_from_magnet_url,
                user_id,
                validation.normalized_url,
            ),
            timeout=get_qbit_api_timeout_seconds(),
        )
        queue_download_policy.mark_qbit_latency(time.monotonic() - started_at)
        queue_download_policy.mark_accepted()
        queue_download_session_state.clear_waiting(user_id)
        await message.answer("Magnet accepted and queued for download.")
    except ValidationError as exc:
        reason = exc.code
        queue_download_policy.mark_rejection(exc.code)
        await message.answer(exc.user_message)
    except TimeoutError:
        reason = "qbit_timeout"
        queue_download_policy.mark_qbit_error()
        await message.answer("Torrent service timed out while queueing this magnet. Please retry.")
    except Exception as exc:
        reason = _map_qbit_error(exc)
        queue_download_policy.mark_qbit_error()
        await message.answer(_map_qbit_user_message(reason))
    finally:
        logger.info(
            "/queuedownload magnet decision user_id=%s size=%s infohash=%s reason=%s",
            user_id,
            len(text),
            infohash,
            reason,
        )


def _map_qbit_error(exc: Exception) -> str:
    message = str(exc).lower()
    if "duplicate" in message or "already" in message:
        return "duplicate"
    if "invalid" in message:
        return "invalid"
    if "timed out" in message or "timeout" in message:
        return "qbit_timeout"
    if "connection" in message or "refused" in message:
        return "qbit_unavailable"
    logger.exception("Unexpected qBittorrent error", exc_info=exc)
    return "qbit_unavailable"


def _map_qbit_user_message(reason: str) -> str:
    if reason == "duplicate":
        return "This torrent is already queued."
    if reason == "invalid":
        return "qBittorrent rejected this torrent input as invalid."
    if reason == "qbit_timeout":
        return "qBittorrent timed out. Please retry in a moment."
    return "Torrent backend is currently unavailable. Please retry later."
