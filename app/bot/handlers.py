"""Bot command handlers (Telethon)."""

from __future__ import annotations

import asyncio
from html import escape
import logging
import os
import secrets
import shlex
import shutil
import time
from pathlib import Path

from telethon import Button, TelegramClient, events

from .auth import AuthService
from .commands import setup_non_whitelisted_commands, setup_whitelisted_commands
from .config import get_auth_db_path, get_owner_user_id
from .routing import Router, command_args
from app.download_links import DownloadLinkService
from app.download_links.config import get_download_link_ttl_hours
from app.torrent import CompletedTorrent, FailedTorrent, TorrentService
from app.torrent.config import (
    get_active_downloads_root,
    get_finished_downloads_root,
    get_finished_download_retention_days,
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

router = Router()
logger = logging.getLogger(__name__)
auth_service = AuthService(
    owner_user_id=get_owner_user_id(),
    db_path=get_auth_db_path(),
)

# Telethon takes parse mode per call; keep HTML everywhere except the one Markdown
# site (the click-to-copy /authenticate token).
_HTML = "html"
_MARKDOWN = "md"


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


def _get_user_display_torrent_name(name: str | None) -> str:
    return (name or "(unnamed torrent)")[:64]


def _format_megabytes_per_second(download_speed_bytes_per_sec: int) -> str:
    return f"{download_speed_bytes_per_sec / 1_000_000:.2f}"


def _get_path_size_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size

    total_size = 0
    for root, _, files in os.walk(path):
        for file_name in files:
            file_path = Path(root) / file_name
            try:
                total_size += file_path.stat().st_size
            except OSError:
                logger.warning("Failed to resolve size for path '%s'", file_path)
    return total_size


def _format_size_gb(path: Path) -> str:
    size_gb = _get_path_size_bytes(path) / (1024 ** 3)
    return f"{size_gb:.2f} GB"


class _CompletionNotifier:
    def __init__(self) -> None:
        self._client: TelegramClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_runtime(self, client: TelegramClient) -> None:
        self._client = client
        self._loop = asyncio.get_running_loop()

    def on_torrent_completed(self, torrent: CompletedTorrent) -> None:
        if torrent.user_id is None:
            logger.warning("Cannot notify torrent completion without user_id hash=%s", torrent.hash)
            return

        if self._client is None or self._loop is None:
            logger.warning("Bot runtime is not bound yet; skipping completion notification hash=%s", torrent.hash)
            return

        future = asyncio.run_coroutine_threadsafe(
            self._send_download_completion_message(torrent),
            self._loop,
        )

        def _handle_result(done_future: asyncio.Future[None]) -> None:
            try:
                done_future.result()
            except Exception:
                logger.exception("Failed to send completion notification hash=%s", torrent.hash)

        future.add_done_callback(_handle_result)

    def on_torrent_failed(self, torrent: FailedTorrent) -> None:
        if torrent.user_id is None:
            logger.warning("Cannot notify torrent failure without user_id hash=%s", torrent.hash)
            return

        if self._client is None or self._loop is None:
            logger.warning("Bot runtime is not bound yet; skipping failure notification hash=%s", torrent.hash)
            return

        future = asyncio.run_coroutine_threadsafe(
            self._send_download_failure_message(torrent),
            self._loop,
        )

        def _handle_result(done_future: asyncio.Future[None]) -> None:
            try:
                done_future.result()
            except Exception:
                logger.exception("Failed to send failure notification hash=%s", torrent.hash)

        future.add_done_callback(_handle_result)

    async def _send_download_completion_message(self, torrent: CompletedTorrent) -> None:
        assert self._client is not None
        assert torrent.user_id is not None

        torrent_name = escape(_get_user_display_torrent_name(torrent.name))
        retention_days = get_finished_download_retention_days()
        link_ttl_hours = get_download_link_ttl_hours()
        text = (
            f"✅ Download finished: <b>{torrent_name}</b>\n"
            f"⏳ Downloaded files are stored for {retention_days} days and deleted after that.\n"
            f"🔗 The download link will be working for {link_ttl_hours} hours.\n"
            "🔁 After the link expires, use /getdownloadlink to access the file/folder again."
        )
        if download_link_service is not None and download_link_service.is_configured():
            content_link: str | None = None
            if torrent.content_path is not None:
                try:
                    content_link = download_link_service.build_user_content_link(
                        user_id=torrent.user_id,
                        content_path=torrent.content_path,
                    )
                except ValueError:
                    logger.warning(
                        "Failed to build content link for completed torrent hash=%s path=%s",
                        torrent.hash,
                        torrent.content_path,
                    )

            if content_link is None:
                content_link = download_link_service.build_user_folder_link(user_id=torrent.user_id)

            if torrent.content_is_directory and "?" in content_link:
                path_part, query_part = content_link.split("?", maxsplit=1)
                if not path_part.endswith("/"):
                    content_link = f"{path_part}/?{query_part}"

            if torrent.content_path is not None and not torrent.content_is_directory:
                quoted_output_name = shlex.quote(torrent.content_path.name)
                quoted_content_link = shlex.quote(content_link)
                wget_script = (
                    "wget --no-host-directories "
                    f"--output-document {quoted_output_name} "
                    f"{quoted_content_link}"
                )
            else:
                wget_script = (
                    "wget --recursive --no-parent --no-host-directories --cut-dirs=1 "
                    '--reject "index.html*" "'
                    f"{content_link}"
                    '"'
                )
            text = (
                f"{text}\n\nDownload link:\n{escape(content_link)}\n\n"
                "Alternatively, you can download it via terminal. "
                "Run this wget script (it downloads files into your current terminal folder):\n"
                f"<pre>{escape(wget_script)}</pre>"
            )

        await self._client.send_message(torrent.user_id, text, parse_mode=_HTML)

    async def _send_download_failure_message(self, torrent: FailedTorrent) -> None:
        assert self._client is not None
        assert torrent.user_id is not None

        torrent_name = escape(_get_user_display_torrent_name(torrent.name))
        error_state = escape(torrent.state or "unknown")
        await self._client.send_message(
            torrent.user_id,
            (
                "❌ Download failed: "
                f"<b>{torrent_name}</b>\n"
                f"State: <code>{error_state}</code>\n"
                "The torrent was removed from the queue and any partially downloaded files were deleted."
            ),
            parse_mode=_HTML,
        )


completion_notifier = _CompletionNotifier()


def _build_user_storage_path(storage_root: Path, user_id: int) -> Path:
    """Resolve a user storage path under an expected root directory."""
    resolved_root = storage_root.resolve()
    user_storage_path = (resolved_root / str(user_id)).resolve()
    if resolved_root not in user_storage_path.parents:
        raise ValueError("Resolved user storage path is outside expected root")
    return user_storage_path


def _delete_user_download_folders(user_id: int) -> tuple[list[Path], list[Path]]:
    """Delete per-user folders from active and finished downloads roots."""
    deleted_paths: list[Path] = []
    failed_paths: list[Path] = []
    for storage_root in (get_active_downloads_root(), get_finished_downloads_root()):
        user_storage_path = _build_user_storage_path(storage_root, user_id)
        if not user_storage_path.exists():
            continue

        try:
            shutil.rmtree(user_storage_path)
            deleted_paths.append(user_storage_path)
        except OSError:
            logger.exception("Failed to delete user storage path '%s'", user_storage_path)
            failed_paths.append(user_storage_path)

    return deleted_paths, failed_paths


def _with_cancel_hint(text: str) -> str:
    return f"{text} You can run /cancel to cancel the current command."


def _build_cancel_download_keyboard(user_id: int) -> list[list[Button]] | None:
    if torrent_service is None:
        return None

    active_torrents = torrent_service.list_user_queued_torrents(user_id)
    if not active_torrents:
        return None

    return [
        [
            Button.inline(
                _get_user_display_torrent_name(torrent.name),
                data=f"cancel_torrent:{torrent.hash}".encode(),
            )
        ]
        for torrent in active_torrents
    ]


def _build_finished_downloads_keyboard(user_id: int, callback_prefix: str) -> list[list[Button]] | None:
    user_finished_root = _build_user_storage_path(get_finished_downloads_root(), user_id)
    if not user_finished_root.exists() or not user_finished_root.is_dir():
        return None

    entries = sorted(user_finished_root.iterdir(), key=lambda item: item.name.lower())
    if not entries:
        return None

    rows: list[list[Button]] = []
    for index, entry in enumerate(entries):
        rows.append(
            [
                Button.inline(
                    f"{_get_user_display_torrent_name(entry.name)} ({_format_size_gb(entry)})",
                    data=f"{callback_prefix}:{index}".encode(),
                )
            ]
        )

    return rows


def _build_finished_users_keyboard(callback_prefix: str) -> list[list[Button]] | None:
    finished_root = get_finished_downloads_root().resolve()
    if not finished_root.exists() or not finished_root.is_dir():
        return None

    user_dirs = sorted((entry for entry in finished_root.iterdir() if entry.is_dir()), key=lambda item: item.name)
    if not user_dirs:
        return None

    rows: list[list[Button]] = []
    for user_dir in user_dirs:
        user_id = user_dir.name
        rows.append(
            [
                Button.inline(
                    f"User {user_id}",
                    data=f"{callback_prefix}:{user_id}".encode(),
                )
            ]
        )

    return rows


def _delete_finished_download(user_id: int, selected_index: int) -> str:
    user_finished_root = _build_user_storage_path(get_finished_downloads_root(), user_id)
    entries = sorted(user_finished_root.iterdir(), key=lambda item: item.name.lower())
    if selected_index < 0 or selected_index >= len(entries):
        raise ValueError("invalid_selection")

    selected_path = entries[selected_index].resolve()
    if user_finished_root not in selected_path.parents:
        raise ValueError("invalid_selection")

    if not selected_path.exists():
        raise FileNotFoundError("selected_download_missing")

    selected_name_display = escape(_get_user_display_torrent_name(selected_path.name))
    if selected_path.is_dir():
        shutil.rmtree(selected_path)
    else:
        selected_path.unlink()

    return f"🗑 Deleted: <b>{selected_name_display}</b>"


def _parse_user_id(raw_user_id: str) -> int:
    try:
        return int(raw_user_id)
    except ValueError as exc:
        raise ValueError("invalid_user_id") from exc


def _build_finished_download_reply(user_id: int, selected_index: int) -> str:
    if download_link_service is None or not download_link_service.is_configured():
        raise ValueError("download_links_not_configured")

    user_finished_root = _build_user_storage_path(get_finished_downloads_root(), user_id)
    entries = sorted(user_finished_root.iterdir(), key=lambda item: item.name.lower())
    if selected_index < 0 or selected_index >= len(entries):
        raise ValueError("invalid_selection")

    selected_path = entries[selected_index].resolve()
    if user_finished_root not in selected_path.parents:
        raise ValueError("invalid_selection")

    if not selected_path.exists():
        raise FileNotFoundError("selected_download_missing")

    content_link = download_link_service.build_user_content_link(user_id=user_id, content_path=selected_path)
    selected_name_display = escape(_get_user_display_torrent_name(selected_path.name))

    if selected_path.is_file():
        quoted_output_name = shlex.quote(selected_path.name)
        quoted_content_link = shlex.quote(content_link)
        wget_script = (
            "wget --no-host-directories "
            f"--output-document {quoted_output_name} "
            f"{quoted_content_link}"
        )
    else:
        if "?" in content_link:
            path_part, query_part = content_link.split("?", maxsplit=1)
            if not path_part.endswith("/"):
                content_link = f"{path_part}/?{query_part}"

        wget_script = (
            "wget --recursive --no-parent --no-host-directories --cut-dirs=1 "
            '--reject "index.html*" "'
            f"{content_link}"
            '"'
        )

    return (
        f"✅ Download ready: <b>{selected_name_display}</b>\n\n"
        f"Download link (valid for {get_download_link_ttl_hours()} hours):\n{escape(content_link)}\n\n"
        "Alternatively, you can download it via terminal. "
        "Run this wget script (it downloads files into your current terminal folder):\n"
        f"<pre>{escape(wget_script)}</pre>"
    )


def _build_download_link_service() -> DownloadLinkService | None:
    try:
        return DownloadLinkService()
    except ValueError:
        return None


def _build_torrent_service() -> TorrentService | None:
    try:
        return TorrentService(
            default_owner_user_id=get_owner_user_id(),
            on_torrent_completed=completion_notifier.on_torrent_completed,
            on_torrent_failed=completion_notifier.on_torrent_failed,
        )
    except ValueError:
        logger.exception("Failed to initialize TorrentService")
        return None


download_link_service = _build_download_link_service()
torrent_service = _build_torrent_service()


def bind_runtime_client(client: TelegramClient) -> None:
    """Bind active client/loop so background workers can send Telegram notifications."""
    completion_notifier.bind_runtime(client)


def install_handlers(client: TelegramClient) -> None:
    """Attach the router's message/callback dispatchers to the client."""
    router.install(client)


async def _get_actor(event) -> tuple[int, str | None] | None:
    user_id = event.sender_id
    if user_id is None:
        return None
    username: str | None = None
    try:
        sender = await event.get_sender()
        username = getattr(sender, "username", None) if sender else None
    except Exception:
        logger.debug("Failed to resolve sender username for user_id=%s", user_id)
    return user_id, username


async def _require_admin(event) -> tuple[int, str | None] | None:
    actor = await _get_actor(event)
    if actor is None:
        await event.respond("Cannot resolve caller identity.")
        return None

    user_id, _ = actor
    if not auth_service.is_admin(user_id=user_id):
        await event.respond("This command is admin-only.")
        return None
    return actor


async def _require_whitelisted(event) -> tuple[int, str | None] | None:
    actor = await _get_actor(event)
    if actor is None:
        await event.respond("Cannot resolve caller identity.")
        return None

    user_id, _ = actor
    if not auth_service.is_whitelisted(user_id):
        await event.respond("You are not authenticated. Use /authenticate <token>.")
        return None
    return actor


@router.command("start")
async def handle_start(event: events.NewMessage.Event) -> None:
    actor = await _get_actor(event)
    if actor is None:
        await event.respond("Cannot resolve caller identity.")
        return

    user_id, _ = actor
    if not auth_service.is_whitelisted(user_id):
        await event.respond(
            "You are not whitelisted yet. Request an access token from the admin and "
            "use /authenticate <token> to get whitelisted before using the bot."
        )
        return

    await event.respond("Welcome! Use /queuedownload to submit a torrent or magnet link.")


@router.command("queuedownload")
async def handle_queuedownload(event: events.NewMessage.Event) -> None:
    actor = await _require_whitelisted(event)
    if actor is None:
        return

    user_id, _ = actor
    if not queue_download_policy.enforce_rate_limit(user_id):
        await event.respond("Too many queue requests right now. Please wait a minute and try again.")
        return

    queue_download_session_state.begin_waiting(user_id=user_id, command="queuedownload")
    await event.respond("Paste a magnet URL or upload a .torrent file.")


@router.command("cancel")
async def handle_cancel(event: events.NewMessage.Event) -> None:
    actor = await _get_actor(event)
    if actor is None:
        await event.respond("Cannot resolve caller identity.")
        return

    user_id, _ = actor
    waiting_command = queue_download_session_state.get_waiting_command(user_id)
    if waiting_command is None:
        await event.respond("There is no pending command input to cancel.")
        return

    queue_download_session_state.clear_waiting(user_id)
    await event.respond(f"Cancelled /{waiting_command} input.")


@router.command("canceldownload")
async def handle_cancel_download(event: events.NewMessage.Event) -> None:
    actor = await _require_whitelisted(event)
    if actor is None:
        return

    if torrent_service is None:
        await event.respond("Torrent service is currently unavailable. Please contact admin.")
        return

    user_id, _ = actor
    try:
        keyboard = await asyncio.wait_for(
            asyncio.to_thread(_build_cancel_download_keyboard, user_id),
            timeout=get_qbit_api_timeout_seconds(),
        )
    except TimeoutError:
        await event.respond(_map_qbit_user_message("qbit_timeout"))
        return
    except Exception as exc:
        reason = _map_qbit_error(exc)
        await event.respond(_map_qbit_user_message(reason))
        return

    if keyboard is None:
        await event.respond("You have no active downloads to cancel.")
        return

    await event.respond("Select a download to cancel and delete:", buttons=keyboard)


@router.callback("cancel_torrent:")
async def handle_cancel_torrent_click(event: events.CallbackQuery.Event) -> None:
    actor = await _get_actor(event)
    if actor is None:
        await event.answer("Cannot resolve caller identity.", alert=True)
        return

    user_id, _ = actor
    if not auth_service.is_whitelisted(user_id):
        await event.answer("You are not authenticated.", alert=True)
        return

    if torrent_service is None:
        await event.answer("Torrent service unavailable.", alert=True)
        return

    callback_data = (event.data or b"").decode()
    torrent_hash = callback_data.partition(":")[2].strip()
    if not torrent_hash:
        await event.answer("Invalid torrent selection.", alert=True)
        return

    try:
        cancelled = await asyncio.wait_for(
            asyncio.to_thread(torrent_service.cancel_user_torrent, user_id, torrent_hash),
            timeout=get_qbit_api_timeout_seconds(),
        )
    except TimeoutError:
        await event.answer(_map_qbit_user_message("qbit_timeout"), alert=True)
        return
    except Exception as exc:
        reason = _map_qbit_error(exc)
        await event.answer(_map_qbit_user_message(reason), alert=True)
        return

    if not cancelled:
        await event.answer("Download is no longer active.", alert=True)
        return

    await event.answer("Download cancelled.")

    try:
        keyboard = await asyncio.wait_for(
            asyncio.to_thread(_build_cancel_download_keyboard, user_id),
            timeout=get_qbit_api_timeout_seconds(),
        )
    except Exception:
        keyboard = None

    if keyboard is None:
        await event.edit("No active downloads left to cancel.")
        return

    await event.edit("Select a download to cancel and delete:", buttons=keyboard)


@router.command("status")
async def handle_status(event: events.NewMessage.Event) -> None:
    actor = await _require_whitelisted(event)
    if actor is None:
        return

    if torrent_service is None:
        await event.respond("Torrent service is currently unavailable. Please contact admin.")
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
        await event.respond(_map_qbit_user_message("qbit_timeout"))
        return
    except Exception as exc:
        reason = _map_qbit_error(exc)
        await event.respond(_map_qbit_user_message(reason))
        return

    if not queued_torrents:
        await event.respond("You have no active queued torrents.")
        return

    lines = ["Your active torrents:"]
    for torrent in queued_torrents:
        torrent_name = escape(_get_user_display_torrent_name(torrent.name))
        torrent_state = escape(torrent.state or "unknown")
        speed_suffix = ""
        if torrent.dlspeed_bytes_per_sec is not None:
            speed_suffix = f" | Speed: <b>{_format_megabytes_per_second(torrent.dlspeed_bytes_per_sec)} MB/s</b>"
        lines.append(
            f"• {torrent_name} — State: <b>{torrent_state}</b> | Downloaded: <b>{torrent.progress_percent:.1f}%</b>"
            f"{speed_suffix}"
        )

    await event.respond("\n".join(lines), parse_mode=_HTML)


@router.command("myfolder")
async def handle_myfolder(event: events.NewMessage.Event) -> None:
    actor = await _require_whitelisted(event)
    if actor is None:
        return

    if download_link_service is None or not download_link_service.is_configured():
        await event.respond(
            "Folder links are not configured yet. Please ask admin to configure HFS_BASE_URL "
            "and DOWNLOAD_LINK_SECRET."
        )
        return

    user_id, _ = actor
    folder_link = download_link_service.build_user_folder_link(user_id=user_id)
    await event.respond(
        f"Your personal download folder link (valid for {get_download_link_ttl_hours()} hours):\n"
        f"{folder_link}\n\n"
        "This link is scoped to your Telegram user folder only."
    )


@router.command("deletefiles")
async def handle_deletefiles(event: events.NewMessage.Event) -> None:
    actor = await _require_whitelisted(event)
    if actor is None:
        return

    user_id, _ = actor
    if auth_service.is_admin(user_id=user_id):
        keyboard = await asyncio.to_thread(_build_finished_users_keyboard, "delete_user_files")
        if keyboard is None:
            await event.respond("No user folders with finished downloads found.")
            return

        await event.respond("Select a user folder to manage files:", buttons=keyboard)
        return

    try:
        keyboard = await asyncio.to_thread(_build_finished_downloads_keyboard, user_id, "delete_file")
    except ValueError:
        await event.respond("Failed to resolve your finished downloads folder.")
        return

    if keyboard is None:
        await event.respond("No finished downloads found in your folder yet.")
        return

    await event.respond("Select a finished download to delete:", buttons=keyboard)


@router.callback("delete_user_files:")
async def handle_delete_user_files_click(event: events.CallbackQuery.Event) -> None:
    actor = await _get_actor(event)
    if actor is None:
        await event.answer("Cannot resolve caller identity.", alert=True)
        return

    user_id, _ = actor
    if not auth_service.is_admin(user_id=user_id):
        await event.answer("This action is admin-only.", alert=True)
        return

    callback_data = (event.data or b"").decode()
    selected_user_token = callback_data.partition(":")[2].strip()
    if not selected_user_token:
        await event.answer("Invalid selection.", alert=True)
        return

    try:
        selected_user_id = _parse_user_id(selected_user_token)
    except ValueError:
        await event.answer("Invalid selection.", alert=True)
        return

    try:
        keyboard = await asyncio.to_thread(
            _build_finished_downloads_keyboard, selected_user_id, f"delete_admin_file:{selected_user_id}"
        )
    except ValueError:
        await event.answer("Failed to resolve selected user folder.", alert=True)
        return

    if keyboard is None:
        await event.answer("This user has no finished downloads.", alert=True)
        return

    await event.answer()
    await event.edit(
        f"Selected user <code>{selected_user_id}</code>. Choose a file/folder to delete:",
        buttons=keyboard,
        parse_mode=_HTML,
    )


@router.command("getdownloadlink")
async def handle_getdownloadlink(event: events.NewMessage.Event) -> None:
    actor = await _require_whitelisted(event)
    if actor is None:
        return

    user_id, _ = actor
    try:
        keyboard = await asyncio.to_thread(_build_finished_downloads_keyboard, user_id, "download_link")
    except ValueError:
        await event.respond("Failed to resolve your finished downloads folder.")
        return

    if keyboard is None:
        await event.respond("No finished downloads found in your folder yet.")
        return

    await event.respond(
        f"Select a finished download to get its direct link (valid for {get_download_link_ttl_hours()} hours):",
        buttons=keyboard,
    )


@router.callback("download_link:")
async def handle_download_link_click(event: events.CallbackQuery.Event) -> None:
    actor = await _get_actor(event)
    if actor is None:
        await event.answer("Cannot resolve caller identity.", alert=True)
        return

    user_id, _ = actor
    if not auth_service.is_whitelisted(user_id):
        await event.answer("You are not authenticated.", alert=True)
        return

    callback_data = (event.data or b"").decode()
    selection_token = callback_data.partition(":")[2].strip()
    if not selection_token:
        await event.answer("Invalid selection.", alert=True)
        return

    try:
        selected_index = int(selection_token)
    except ValueError:
        await event.answer("Invalid selection.", alert=True)
        return

    await event.answer()

    try:
        reply_text = await asyncio.to_thread(_build_finished_download_reply, user_id, selected_index)
    except FileNotFoundError:
        await event.respond("That download no longer exists. Run /getdownloadlink again.")
        return
    except ValueError as exc:
        if str(exc) == "download_links_not_configured":
            await event.respond(
                "Folder links are not configured yet. Please ask admin to configure HFS_BASE_URL "
                "and DOWNLOAD_LINK_SECRET."
            )
            return

        await event.respond("Invalid selection. Run /getdownloadlink again.")
        return

    await event.respond(reply_text, parse_mode=_HTML)


@router.callback("delete_file:")
async def handle_delete_file_click(event: events.CallbackQuery.Event) -> None:
    actor = await _get_actor(event)
    if actor is None:
        await event.answer("Cannot resolve caller identity.", alert=True)
        return

    user_id, _ = actor
    if not auth_service.is_whitelisted(user_id):
        await event.answer("You are not authenticated.", alert=True)
        return

    callback_data = (event.data or b"").decode()
    selection_token = callback_data.partition(":")[2].strip()
    if not selection_token:
        await event.answer("Invalid selection.", alert=True)
        return

    try:
        selected_index = int(selection_token)
    except ValueError:
        await event.answer("Invalid selection.", alert=True)
        return

    try:
        deleted_text = await asyncio.to_thread(_delete_finished_download, user_id, selected_index)
    except FileNotFoundError:
        await event.answer("That download no longer exists.", alert=True)
        return
    except ValueError:
        await event.answer("Invalid selection.", alert=True)
        return
    except OSError:
        await event.answer("Failed to delete selected download.", alert=True)
        return

    await event.answer("Deleted.")

    try:
        keyboard = await asyncio.to_thread(_build_finished_downloads_keyboard, user_id, "delete_file")
    except ValueError:
        keyboard = None

    if keyboard is None:
        await event.edit(f"{deleted_text}\n\nNo finished downloads left.", parse_mode=_HTML)
        return

    await event.edit(
        f"{deleted_text}\n\nSelect a finished download to delete:",
        buttons=keyboard,
        parse_mode=_HTML,
    )


@router.callback("delete_admin_file:")
async def handle_delete_admin_file_click(event: events.CallbackQuery.Event) -> None:
    actor = await _get_actor(event)
    if actor is None:
        await event.answer("Cannot resolve caller identity.", alert=True)
        return

    user_id, _ = actor
    if not auth_service.is_admin(user_id=user_id):
        await event.answer("This action is admin-only.", alert=True)
        return

    callback_data = (event.data or b"").decode()
    parts = callback_data.split(":", maxsplit=2)
    if len(parts) != 3:
        await event.answer("Invalid selection.", alert=True)
        return

    _, selected_user_token, selection_token = parts

    try:
        selected_user_id = _parse_user_id(selected_user_token)
        selected_index = int(selection_token)
    except ValueError:
        await event.answer("Invalid selection.", alert=True)
        return

    try:
        deleted_text = await asyncio.to_thread(_delete_finished_download, selected_user_id, selected_index)
    except FileNotFoundError:
        await event.answer("That download no longer exists.", alert=True)
        return
    except ValueError:
        await event.answer("Invalid selection.", alert=True)
        return
    except OSError:
        await event.answer("Failed to delete selected download.", alert=True)
        return

    await event.answer("Deleted.")

    try:
        keyboard = await asyncio.to_thread(
            _build_finished_downloads_keyboard,
            selected_user_id,
            f"delete_admin_file:{selected_user_id}",
        )
    except ValueError:
        keyboard = None

    if keyboard is None:
        await event.edit(
            f"{deleted_text}\n\nNo finished downloads left for user <code>{selected_user_id}</code>.",
            parse_mode=_HTML,
        )
        return

    await event.edit(
        f"{deleted_text}\n\nSelected user <code>{selected_user_id}</code>. Choose a file/folder to delete:",
        buttons=keyboard,
        parse_mode=_HTML,
    )


@router.command("generateaccesstoken")
async def handle_generate_access_token(event: events.NewMessage.Event) -> None:
    if await _require_admin(event) is None:
        return

    token = auth_service.generate_access_token()
    await event.respond(
        "Here is your access token command. Click the code below to copy it, "
        "then paste and send it to the bot.\n"
        "Valid for 30 minutes and single-use:\n"
        f"`/authenticate {token}`",
        parse_mode=_MARKDOWN,
    )


@router.command("authenticate")
async def handle_authenticate(event: events.NewMessage.Event) -> None:
    actor = await _get_actor(event)
    if actor is None:
        await event.respond("Cannot resolve caller identity.")
        return

    user_id, username = actor
    if auth_service.is_whitelisted(user_id):
        await event.respond("You are already whitelisted. Auth token was not consumed.")
        return

    token = command_args(event.raw_text)
    if not token:
        await event.respond("Usage: /authenticate <token>")
        return

    if auth_service.authenticate_user(token=token, user_id=user_id, username=username):
        await event.respond("Authentication successful. You are now whitelisted.")
        await setup_whitelisted_commands(
            client=event.client,
            user_id=user_id,
            is_admin=auth_service.is_admin(user_id=user_id),
        )
        owner_user_id = get_owner_user_id()
        if owner_user_id is not None:
            username_display = f"@{username}" if username else "<none>"
            await event.client.send_message(
                owner_user_id,
                (
                    "User authenticated successfully:\n"
                    f"- user_id: <code>{user_id}</code>\n"
                    f"- username: {escape(username_display)}"
                ),
                parse_mode=_HTML,
            )
        return

    await event.respond("Invalid or expired token.")


@router.command("removeuser")
async def handle_removeuser(event: events.NewMessage.Event) -> None:
    if await _require_admin(event) is None:
        return

    raw_user_id = command_args(event.raw_text)
    if not raw_user_id:
        await event.respond("Usage: /removeuser <user_id>")
        return

    try:
        target_user_id = int(raw_user_id)
    except ValueError:
        await event.respond("user_id must be an integer.")
        return

    if auth_service.remove_user(target_user_id):
        await setup_non_whitelisted_commands(client=event.client, user_id=target_user_id)
        _, failed_paths = _delete_user_download_folders(target_user_id)
        if failed_paths:
            failed_paths_display = "\n".join(f"- <code>{escape(str(path))}</code>" for path in failed_paths)
            await event.respond(
                (
                    f"Removed user {target_user_id} from whitelist.\n"
                    "However, some user folders could not be deleted:\n"
                    f"{failed_paths_display}"
                ),
                parse_mode=_HTML,
            )
            return

        await event.respond(
            f"Removed user {target_user_id} from whitelist and deleted their download folders."
        )
        return

    await event.respond(f"User {target_user_id} is not whitelisted.")


@router.command("whitelist")
async def handle_whitelist(event: events.NewMessage.Event) -> None:
    if await _require_admin(event) is None:
        return

    users = auth_service.list_whitelisted_users()
    if not users:
        await event.respond("Whitelist is empty.")
        return

    lines = ["Whitelisted users:"]
    for user in users:
        username = user.username_at_authentication
        username_display = f"@{username}" if username else "<none>"
        lines.append(
            f"- user_id=<code>{user.user_id}</code>, "
            f"username_at_authentication={escape(username_display)}"
        )

    await event.respond("\n".join(lines), parse_mode=_HTML)


@router.command("availablespace")
async def handle_availablespace(event: events.NewMessage.Event) -> None:
    if await _require_admin(event) is None:
        return

    usage = shutil.disk_usage(get_finished_downloads_root())
    available_gb = usage.free / (1024 ** 3)
    await event.respond(f"Available disk space: {available_gb:.2f} GB")


@router.fallback()
async def handle_queue_download_input(event: events.NewMessage.Event) -> None:
    actor = await _get_actor(event)
    if actor is None:
        return

    user_id, _ = actor
    if not queue_download_session_state.is_waiting(user_id):
        return

    if not auth_service.is_whitelisted(user_id):
        queue_download_session_state.clear_waiting(user_id)
        await event.respond("You are not authenticated. Use /authenticate <token>.")
        return

    if torrent_service is None:
        queue_download_session_state.clear_waiting(user_id)
        await event.respond("Torrent service is currently unavailable. Please contact admin.")
        return

    if event.document is not None:
        await _process_queue_download_torrent_upload(event=event, user_id=user_id)
        return

    text = (event.raw_text or "").strip()
    if text:
        await _process_queue_download_magnet_input(event=event, user_id=user_id, text=text)
        return

    await event.respond(_with_cancel_hint("Please paste a magnet URL or upload a .torrent file."))


async def _process_queue_download_torrent_upload(event: events.NewMessage.Event, user_id: int) -> None:
    assert event.document is not None
    uploaded_file = event.file
    original_name = (uploaded_file.name if uploaded_file else None) or "upload.torrent"
    file_size = uploaded_file.size if uploaded_file else None
    if not original_name.lower().endswith(".torrent"):
        await event.respond(_with_cancel_hint("Please upload a .torrent file."))
        queue_download_policy.mark_rejection("torrent_extension")
        return

    if file_size is not None and file_size > get_max_torrent_bytes_hard():
        await event.respond(_with_cancel_hint("Torrent file is too large."))
        queue_download_policy.mark_rejection("torrent_size_hard")
        logger.info("/queuedownload rejected upload user_id=%s reason=%s size=%s", user_id, "torrent_size_hard", file_size)
        return

    temp_input_dir = get_torrent_input_tmp_dir()
    temp_input_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_input_dir / f"{secrets.token_hex(16)}.torrent"
    infohash: str | None = None
    reason = "accepted"
    try:
        await event.message.download_media(file=str(temp_path))
        torrent_bytes = temp_path.read_bytes()

        if len(torrent_bytes) > get_max_torrent_bytes_hard():
            queue_download_policy.mark_rejection("torrent_size_hard")
            await event.respond(_with_cancel_hint("Torrent file is too large."))
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

        is_duplicate = await asyncio.wait_for(
            asyncio.to_thread(torrent_service.is_torrent_already_queued, infohash),
            timeout=get_qbit_api_timeout_seconds(),
        )
        if is_duplicate:
            reason = "duplicate"
            queue_download_policy.mark_rejection("duplicate")
            queue_download_session_state.clear_waiting(user_id)
            await event.respond("This torrent is already queued.")
            return

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
        await event.respond("Download queued successfully. You'll receive a message once the download completes.\n\nUse /status to check progress. The bot checks completion every 30 seconds, so if /status is empty but you haven't received the completion message yet, please wait up to 30 seconds.")
    except ValidationError as exc:
        reason = exc.code
        queue_download_policy.mark_rejection(exc.code)
        await event.respond(_with_cancel_hint(exc.user_message))
    except TimeoutError:
        reason = "qbit_timeout"
        queue_download_policy.mark_qbit_error()
        await event.respond("Torrent service timed out while queueing this torrent. Please retry.")
    except Exception as exc:
        reason = _map_qbit_error(exc)
        queue_download_policy.mark_qbit_error()
        await event.respond(_map_qbit_user_message(reason))
    finally:
        logger.info(
            "/queuedownload torrent upload decision user_id=%s size=%s infohash=%s reason=%s",
            user_id,
            file_size,
            infohash,
            reason,
        )
        temp_path.unlink(missing_ok=True)


async def _process_queue_download_magnet_input(event: events.NewMessage.Event, user_id: int, text: str) -> None:
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
            await event.respond("Torrent service is currently unavailable. Please contact admin.")
            return

        is_duplicate = await asyncio.wait_for(
            asyncio.to_thread(torrent_service.is_torrent_already_queued, infohash),
            timeout=get_qbit_api_timeout_seconds(),
        )
        if is_duplicate:
            reason = "duplicate"
            queue_download_policy.mark_rejection("duplicate")
            queue_download_session_state.clear_waiting(user_id)
            await event.respond("This torrent is already queued.")
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
        await event.respond("Download queued successfully. You'll receive a message once the download completes.\n\nUse /status to check progress. The bot checks completion every 30 seconds, so if /status is empty but you haven't received the completion message yet, please wait up to 30 seconds.")
    except ValidationError as exc:
        reason = exc.code
        queue_download_policy.mark_rejection(exc.code)
        await event.respond(_with_cancel_hint(exc.user_message))
    except TimeoutError:
        reason = "qbit_timeout"
        queue_download_policy.mark_qbit_error()
        await event.respond("Torrent service timed out while queueing this magnet. Please retry.")
    except Exception as exc:
        reason = _map_qbit_error(exc)
        queue_download_policy.mark_qbit_error()
        await event.respond(_map_qbit_user_message(reason))
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
