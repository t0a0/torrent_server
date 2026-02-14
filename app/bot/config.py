"""Configuration helpers for bot initialization."""

import os

from app.config import load_env_file

_BOT_TOKEN_KEY = "TELEGRAM_BOT_TOKEN"
_OWNER_USER_ID_KEY = "BOT_OWNER_USER_ID"



def get_bot_token() -> str:
    """Resolve bot token from environment, loading it from .env if needed."""
    load_env_file()
    token = os.getenv(_BOT_TOKEN_KEY)
    if not token:
        raise ValueError(f"Missing required environment variable: {_BOT_TOKEN_KEY}")
    return token


def get_owner_user_id() -> int | None:
    """Resolve optional bot owner user id used for admin-only commands."""
    load_env_file()
    raw_user_id = os.getenv(_OWNER_USER_ID_KEY)
    if not raw_user_id:
        return None

    try:
        return int(raw_user_id)
    except ValueError as exc:
        raise ValueError(f"Invalid integer in {_OWNER_USER_ID_KEY}: {raw_user_id}") from exc

