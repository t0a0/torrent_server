"""Persistent, hot-reloadable proxy list backing the bot's failover loop.

The live proxy configuration lives in a small JSON file on the ``/auth`` volume
(already bind-mounted and persistent). Keeping it on disk rather than in ``.env`` is
what lets the admin page and the automatic failover loop change proxies without a
restart: every read re-parses the file, so an edit takes effect on the next reconnect.

File shape::

    {"proxies": ["tg://proxy?server=...", "host:port:secret", "direct"],
     "active_index": 0}

On first boot the file is seeded from ``TELEGRAM_MTPROXY`` in ``.env``; after that the
file is the single source of truth. Writes are atomic (temp file + ``os.replace``) so
the admin thread can rewrite it while the asyncio loop reads it, with no locking.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .mtproxy import Proxy, ProxyError, parse_proxy

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProxyList:
    """A snapshot of the stored proxy entries and which one is active."""

    entries: list[str]
    active_index: int


class ProxyStore:
    """Read/rotate/replace the on-disk proxy list.

    Every method re-reads the file, so the store holds no cached mutable state and is
    safe to share between the web thread and the bot loop.
    """

    def __init__(self, path: Path, seed: str | None = None) -> None:
        self._path = path
        self._seed = seed
        self._ensure_seeded()

    # -- persistence -------------------------------------------------------

    def _ensure_seeded(self) -> None:
        if self._path.exists():
            return
        seed_entries = _split_seed(self._seed) or ["direct"]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._write(ProxyList(entries=seed_entries, active_index=0))
        logger.info(
            "Seeded proxy store at %s with %d entr%s",
            self._path,
            len(seed_entries),
            "y" if len(seed_entries) == 1 else "ies",
        )

    def _read(self) -> ProxyList:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            entries = [str(item) for item in data.get("proxies", [])]
            active_index = int(data.get("active_index", 0))
        except (OSError, ValueError, TypeError):
            logger.exception("Proxy store at %s is unreadable; falling back to direct", self._path)
            return ProxyList(entries=["direct"], active_index=0)

        if not entries:
            entries = ["direct"]
        active_index %= len(entries)
        return ProxyList(entries=entries, active_index=active_index)

    def _write(self, proxy_list: ProxyList) -> None:
        payload = json.dumps(
            {"proxies": proxy_list.entries, "active_index": proxy_list.active_index},
            indent=2,
        )
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, self._path)

    # -- reads -------------------------------------------------------------

    def snapshot(self) -> ProxyList:
        """Return the current list and active index (for the admin page)."""
        return self._read()

    def get_active(self) -> Proxy:
        """Return the active proxy, parsed. Falls back to direct on a bad entry."""
        state = self._read()
        raw = state.entries[state.active_index]
        try:
            return parse_proxy(raw)
        except ProxyError:
            logger.exception("Active proxy entry %r is invalid; using direct", raw)
            return parse_proxy("direct")

    # -- mutations ---------------------------------------------------------

    def rotate(self) -> Proxy:
        """Advance to the next entry (wrapping) and return the new active proxy."""
        state = self._read()
        if len(state.entries) > 1:
            next_index = (state.active_index + 1) % len(state.entries)
            self._write(ProxyList(entries=state.entries, active_index=next_index))
            logger.info(
                "Rotated proxy %d -> %d of %d",
                state.active_index,
                next_index,
                len(state.entries),
            )
        return self.get_active()

    def replace_all(self, raw_entries: list[str], active_index: int = 0) -> ProxyList:
        """Validate and persist a new list. Raises :class:`ProxyError` if any entry is bad."""
        cleaned = [line.strip() for line in raw_entries if line.strip()]
        if not cleaned:
            cleaned = ["direct"]
        for entry in cleaned:
            parse_proxy(entry)  # validation; raises ProxyError on bad input
        active_index %= len(cleaned)
        new_list = ProxyList(entries=cleaned, active_index=active_index)
        self._write(new_list)
        logger.info("Replaced proxy list with %d entries", len(cleaned))
        return new_list


def _split_seed(seed: str | None) -> list[str]:
    """Split a ``TELEGRAM_MTPROXY`` seed into entries (comma- or newline-separated)."""
    if not seed:
        return []
    normalized = seed.replace("\n", ",")
    return [part.strip() for part in normalized.split(",") if part.strip()]
