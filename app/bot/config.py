"""Configuration helpers for bot initialization."""

from pathlib import Path
import os

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_BOT_TOKEN_KEY = "TELEGRAM_BOT_TOKEN"


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
