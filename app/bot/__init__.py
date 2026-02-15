"""Bot package with aiogram integration and command handlers."""

from .bot import create_bot
from .handlers import router

__all__ = ["create_bot", "create_dispatcher", "router", "run_bot"]


def __getattr__(name: str):
    """Lazily expose main-module entrypoints without eager import side effects."""
    if name in {"create_dispatcher", "run_bot"}:
        from . import main as _main

        return getattr(_main, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Include lazy exports in module introspection."""
    return sorted(set(globals()) | {"create_dispatcher", "run_bot"})
