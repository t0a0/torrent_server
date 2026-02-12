"""Authentication and authorization helpers."""

from __future__ import annotations

from collections.abc import Set


def is_user_allowed(user_id: int, allowed_user_ids: Set[int]) -> bool:
    """Return whether a Telegram user ID is present in the configured allowlist."""
    return user_id in allowed_user_ids
