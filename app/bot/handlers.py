"""Phase 1 bot command handlers."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="phase1_handlers")


@router.message(Command("start"))
async def handle_start(message: Message) -> None:
    print("/start")


@router.message(Command("add"))
async def handle_add(message: Message) -> None:
    print("/add")


@router.message(Command("adduser"))
async def handle_adduser(message: Message) -> None:
    print("/adduser")


@router.message(Command("removeuser"))
async def handle_removeuser(message: Message) -> None:
    print("/removeuser")


@router.message(Command("whitelist"))
async def handle_whitelist(message: Message) -> None:
    print("/whitelist")
