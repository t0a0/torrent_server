"""ASCII-only renaming of finished payloads so downloads work with any client.

`wget` mangles or 404s on non-ASCII paths (e.g. Cyrillic) depending on its build,
shell and locale, so finished payloads are stored under transliterated names.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from anyascii import anyascii

logger = logging.getLogger(__name__)

_MAX_NAME_LENGTH = 255
_MAX_SUFFIX_LENGTH = 16
_FALLBACK_NAME = "unnamed"
# Characters Windows cannot store in file names, plus control characters.
_NON_PORTABLE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]+')


def to_portable_name(name: str) -> str:
    """Return an ASCII-only name that is valid on Linux, macOS and Windows.

    Apostrophes are dropped: transliteration emits them for soft/hard signs
    (`Фильм` -> `Fil'm`) and they break the shell-quoted single-file `wget`
    command in PowerShell. Already-portable names are returned unchanged.
    """
    transliterated_name = anyascii(name).replace("'", "")
    portable_name = _NON_PORTABLE_CHARS.sub("_", transliterated_name).strip().rstrip(". ")
    return _truncate_name(portable_name or _FALLBACK_NAME)


def make_tree_names_portable(root: Path) -> None:
    """Rename every file and folder below `root` to its portable name, deepest first."""
    for dir_path, dir_names, file_names in os.walk(root, topdown=False):
        parent = Path(dir_path)
        for name in sorted(dir_names + file_names):
            portable_name = to_portable_name(name)
            if portable_name == name:
                continue

            source_path = parent / name
            destination_path = _build_unused_path(parent, portable_name)
            try:
                source_path.rename(destination_path)
            except OSError:
                logger.exception("Failed to rename '%s' to '%s'", source_path, destination_path)


def _build_unused_path(parent: Path, name: str) -> Path:
    """Return `parent / name`, adding a `_<n>` suffix when that path is already taken."""
    candidate = parent / name
    stem, suffix = _split_suffix(name)
    counter = 2
    while os.path.lexists(candidate):
        counter_suffix = f"_{counter}{suffix}"
        candidate = parent / f"{stem[: _MAX_NAME_LENGTH - len(counter_suffix)]}{counter_suffix}"
        counter += 1
    return candidate


def _truncate_name(name: str) -> str:
    if len(name) <= _MAX_NAME_LENGTH:
        return name
    stem, suffix = _split_suffix(name)
    return f"{stem[: _MAX_NAME_LENGTH - len(suffix)]}{suffix}"


def _split_suffix(name: str) -> tuple[str, str]:
    stem, suffix = os.path.splitext(name)
    if len(suffix) > _MAX_SUFFIX_LENGTH:
        return name, ""
    return stem, suffix
