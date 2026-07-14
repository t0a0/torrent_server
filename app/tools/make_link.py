"""Mint a signed file-server folder link from the command line.

Useful when Telegram is unreachable (e.g. blocked at the network edge) and the bot
cannot deliver the link itself. The completion worker still moves finished payloads
into ``finished_downloads/<user_id>/``; this tool produces a browsable link to that
folder using the same signing logic the bot uses.

It prints the signed folder link followed by a ``wget`` command that downloads the
whole folder into the current directory -- the same terminal command the Telegram
bot offers for directory downloads.

Usage:
    python -m app.tools.make_link [user_id]

``user_id`` defaults to ``BOT_OWNER_USER_ID``. A single signed folder link grants
browse + download access to everything under that user's folder until it expires.
"""

from __future__ import annotations

import argparse
import os
import sys

from app.config import load_env_file
from app.download_links import DownloadLinkService

_OWNER_USER_ID_KEY = "BOT_OWNER_USER_ID"


def _get_owner_user_id() -> int | None:
    """Read BOT_OWNER_USER_ID without importing the Telethon-backed bot package."""
    load_env_file()
    raw_user_id = os.getenv(_OWNER_USER_ID_KEY)
    if not raw_user_id:
        return None
    try:
        return int(raw_user_id)
    except ValueError as exc:
        raise ValueError(f"Invalid integer in {_OWNER_USER_ID_KEY}: {raw_user_id}") from exc


def _build_folder_wget_script(folder_link: str) -> str:
    """Mirror the Telegram bot's directory `wget` command for a folder link.

    The folder link already ends with `/` before its query string, so it is used
    as-is (no trailing-slash fix-up needed).
    """
    return (
        "wget --recursive --no-parent --no-host-directories --cut-dirs=1 "
        '--reject "index.html*" "'
        f"{folder_link}"
        '"'
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.tools.make_link",
        description="Generate an expiring signed file-server folder link for a Telegram user id.",
    )
    parser.add_argument(
        "user_id",
        nargs="?",
        type=int,
        default=None,
        help="Telegram user id to link. Defaults to BOT_OWNER_USER_ID.",
    )
    args = parser.parse_args(argv)

    user_id = args.user_id if args.user_id is not None else _get_owner_user_id()
    if user_id is None:
        print(
            "No user_id given and BOT_OWNER_USER_ID is not set.",
            file=sys.stderr,
        )
        return 2

    try:
        service = DownloadLinkService()
    except ValueError as exc:
        print(f"Cannot build download link service: {exc}", file=sys.stderr)
        return 1

    if not service.is_configured():
        print(
            "HFS_BASE_URL is not configured; cannot build a link.",
            file=sys.stderr,
        )
        return 1

    folder_link = service.build_user_folder_link(user_id=user_id)
    print(folder_link)
    print()
    print("# Download everything in this folder into the current directory:")
    print(_build_folder_wget_script(folder_link))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
