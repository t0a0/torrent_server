"""Authentication and authorization helpers."""

from __future__ import annotations

from typing import Any

from app.config import Settings


def is_allowed_telegram_user(user_id: int, settings: Settings) -> bool:
    """Return True when a Telegram user ID is in the configured allowlist."""
    return user_id in settings.telegram_allowed_user_ids


def extract_message_user_id(message: Any) -> int | None:
    """Extract Telegram user ID from a message-like object when available."""
    from_user = getattr(message, "from_user", None)
    if from_user is None:
        return None

    user_id = getattr(from_user, "id", None)
    if user_id is None:
        return None
    return int(user_id)
