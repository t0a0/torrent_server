"""Configuration helpers for bot initialization."""

import os

from app.config import load_env_file

_BOT_TOKEN_KEY = "TELEGRAM_BOT_TOKEN"
_OWNER_USER_ID_KEY = "BOT_OWNER_USER_ID"
_AUTH_DB_PATH_KEY = "AUTH_DB_PATH"
_PROXY_KEY = "TELEGRAM_PROXY"


def get_bot_token() -> str:
    """Resolve bot token from environment, loading it from .env if needed."""
    load_env_file()
    token = os.getenv(_BOT_TOKEN_KEY)
    if not token:
        raise ValueError(f"Missing required environment variable: {_BOT_TOKEN_KEY}")
    return token


def get_telegram_proxy() -> str | None:
    """Resolve an optional proxy URL for reaching Telegram (e.g. when it is blocked).

    Accepts ``socks5://``, ``socks5h://``, ``socks4://`` or ``http://`` URLs. The
    ``socks5h`` scheme is normalized to ``socks5`` because aiogram's SOCKS connector
    already resolves DNS remotely (``rdns=True``); the ``h`` variant just spells that
    behaviour explicitly and is not a scheme aiogram's parser accepts. Returns ``None``
    when unset, so the bot connects to Telegram directly.
    """
    load_env_file()
    proxy = (os.getenv(_PROXY_KEY) or "").strip()
    if not proxy:
        return None
    if proxy.lower().startswith("socks5h://"):
        proxy = "socks5://" + proxy[len("socks5h://"):]
    return proxy


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

def get_auth_db_path() -> str:
    """Resolve path to auth SQLite database file."""
    load_env_file()
    return os.getenv(_AUTH_DB_PATH_KEY, "auth.db")
