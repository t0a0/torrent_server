"""Configuration helpers for bot initialization."""

from pathlib import Path
import os

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_BOT_TOKEN_KEY = "TELEGRAM_BOT_TOKEN"
_OWNER_USER_ID_KEY = "BOT_OWNER_USER_ID"


def load_env_file(env_path: Path = _ENV_FILE) -> None:
    """Load simple KEY=VALUE pairs from a dotenv file into process env."""
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


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

