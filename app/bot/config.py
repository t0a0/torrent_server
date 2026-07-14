"""Configuration helpers for bot initialization."""

import os
from pathlib import Path

from app.config import load_env_file

_BOT_TOKEN_KEY = "TELEGRAM_BOT_TOKEN"
_OWNER_USER_ID_KEY = "BOT_OWNER_USER_ID"
_AUTH_DB_PATH_KEY = "AUTH_DB_PATH"
_API_ID_KEY = "TELEGRAM_API_ID"
_API_HASH_KEY = "TELEGRAM_API_HASH"
_SESSION_PATH_KEY = "TELEGRAM_SESSION_PATH"
_MTPROXY_KEY = "TELEGRAM_MTPROXY"
_PROXY_STORE_PATH_KEY = "TELEGRAM_PROXY_STORE_PATH"
_ADMIN_WEB_USERNAME_KEY = "ADMIN_WEB_USERNAME"
_ADMIN_WEB_PASSWORD_KEY = "ADMIN_WEB_PASSWORD"
_ADMIN_WEB_PORT_KEY = "ADMIN_WEB_PORT"

_DEFAULT_SESSION_PATH = "/auth/bot.session"
_DEFAULT_PROXY_STORE_PATH = "/auth/proxies.json"
_DEFAULT_ADMIN_WEB_PORT = 8082
_MIN_ADMIN_PASSWORD_LENGTH = 16


def get_bot_token() -> str:
    """Resolve bot token from environment, loading it from .env if needed."""
    load_env_file()
    token = os.getenv(_BOT_TOKEN_KEY)
    if not token:
        raise ValueError(f"Missing required environment variable: {_BOT_TOKEN_KEY}")
    return token


def get_api_id() -> int:
    """Resolve the Telegram API id (from my.telegram.org).

    Required in addition to the bot token: Telethon speaks MTProto, which always needs
    an api_id/api_hash pair even for bot logins.
    """
    load_env_file()
    raw_api_id = os.getenv(_API_ID_KEY)
    if not raw_api_id:
        raise ValueError(f"Missing required environment variable: {_API_ID_KEY}")
    try:
        return int(raw_api_id)
    except ValueError as exc:
        raise ValueError(f"Invalid integer in {_API_ID_KEY}: {raw_api_id}") from exc


def get_api_hash() -> str:
    """Resolve the Telegram API hash (from my.telegram.org)."""
    load_env_file()
    api_hash = os.getenv(_API_HASH_KEY)
    if not api_hash:
        raise ValueError(f"Missing required environment variable: {_API_HASH_KEY}")
    return api_hash


def get_session_path() -> str:
    """Resolve the Telethon session path (persisted on the /auth volume)."""
    load_env_file()
    return os.getenv(_SESSION_PATH_KEY, _DEFAULT_SESSION_PATH)


def get_mtproxy_seed() -> str | None:
    """Resolve the optional TELEGRAM_MTPROXY seed used to first-populate the store."""
    load_env_file()
    return os.getenv(_MTPROXY_KEY) or None


def get_proxy_store_path() -> Path:
    """Resolve the path to the JSON proxy store on the /auth volume."""
    load_env_file()
    return Path(os.getenv(_PROXY_STORE_PATH_KEY, _DEFAULT_PROXY_STORE_PATH))


def get_admin_web_credentials() -> tuple[str, str] | None:
    """Resolve admin-page basic-auth credentials, or None if the page is disabled.

    Returns ``None`` when either credential is unset (the page then does not start).
    Raises if a password is set but too short to be safe on the public internet.
    """
    load_env_file()
    username = os.getenv(_ADMIN_WEB_USERNAME_KEY)
    password = os.getenv(_ADMIN_WEB_PASSWORD_KEY)
    if not username or not password:
        return None
    if len(password) < _MIN_ADMIN_PASSWORD_LENGTH:
        raise ValueError(
            f"{_ADMIN_WEB_PASSWORD_KEY} must be at least {_MIN_ADMIN_PASSWORD_LENGTH} "
            "characters; the admin page is exposed to the public internet."
        )
    return username, password


def get_admin_web_port() -> int:
    """Resolve the port the admin page listens on inside the container."""
    load_env_file()
    raw_port = os.getenv(_ADMIN_WEB_PORT_KEY)
    if not raw_port:
        return _DEFAULT_ADMIN_WEB_PORT
    try:
        return int(raw_port)
    except ValueError as exc:
        raise ValueError(f"Invalid integer in {_ADMIN_WEB_PORT_KEY}: {raw_port}") from exc


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
