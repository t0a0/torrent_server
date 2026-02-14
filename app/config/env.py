"""Environment file loading helpers shared across app modules."""

from pathlib import Path
import os

_DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def load_env_file(env_path: Path = _DEFAULT_ENV_FILE) -> None:
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
