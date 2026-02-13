"""Helpers to integrate bot routers into aiogram dispatcher."""

from aiogram import Dispatcher

from .handlers import router


def include_handlers(dispatcher: Dispatcher) -> None:
    """Attach all bot handlers to the provided dispatcher."""
    dispatcher.include_router(router)
