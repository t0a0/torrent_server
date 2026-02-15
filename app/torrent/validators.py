"""Validation gates for torrent files and magnet URLs."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse, unquote
import re

from .policy import (
    get_max_magnet_trackers,
    get_max_magnet_url_length,
    get_max_torrent_aggregate_bytes,
    get_max_torrent_bytes_hard,
    get_max_torrent_bytes_warn,
    get_max_torrent_file_count,
    get_max_torrent_name_length,
    get_max_torrent_path_segment_length,
    get_max_torrent_tracker_url_length,
)


_BTih_RE = re.compile(r"^urn:btih:([A-Za-z0-9]+)$")
_HEX40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_BASE32_RE = re.compile(r"^[A-Z2-7]{32}$")

def _has_invalid_percent_encoding(value: str) -> bool:
    idx = 0
    while True:
        idx = value.find("%", idx)
        if idx == -1:
            return False
        if idx + 2 >= len(value):
            return True
        pair = value[idx + 1 : idx + 3]
        if not all(ch in "0123456789abcdefABCDEF" for ch in pair):
            return True
        idx += 3


class ValidationError(ValueError):
    """Structured validation failure with user-safe message."""

    def __init__(self, reason_code: str, user_message: str) -> None:
        super().__init__(user_message)
        self.reason_code = reason_code
        self.user_message = user_message


@dataclass(slots=True)
class TorrentFileValidationResult:
    infohash: str
    size_bytes: int


@dataclass(slots=True)
class MagnetValidationResult:
    infohash: str
    normalized_magnet: str


class _BencodeDecoder:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._idx = 0

    def decode(self) -> Any:
        value = self._parse_value()
        if self._idx != len(self._data):
            raise ValidationError("torrent_bencode_trailing", "Torrent file contains trailing data.")
        return value

    def _parse_value(self) -> Any:
        if self._idx >= len(self._data):
            raise ValidationError("torrent_bencode_eof", "Torrent file bencode payload is truncated.")

        marker = self._data[self._idx : self._idx + 1]
        if marker == b"i":
            return self._parse_int()
        if marker == b"l":
            return self._parse_list()
        if marker == b"d":
            return self._parse_dict()
        if marker.isdigit():
            return self._parse_bytes()
        raise ValidationError("torrent_bencode_marker", "Torrent file has invalid bencode markers.")

    def _parse_int(self) -> int:
        self._idx += 1
        end = self._data.find(b"e", self._idx)
        if end == -1:
            raise ValidationError("torrent_bencode_int", "Torrent file has malformed integer fields.")
        raw = self._data[self._idx : end]
        self._idx = end + 1
        if not raw:
            raise ValidationError("torrent_bencode_int", "Torrent file has malformed integer fields.")
        if raw.startswith(b"-"):
            digits = raw[1:]
            if not digits or digits.startswith(b"0"):
                raise ValidationError("torrent_bencode_int", "Torrent file has malformed integer fields.")
        elif len(raw) > 1 and raw.startswith(b"0"):
            raise ValidationError("torrent_bencode_int", "Torrent file has malformed integer fields.")
        try:
            return int(raw)
        except ValueError as exc:
            raise ValidationError("torrent_bencode_int", "Torrent file has malformed integer fields.") from exc

    def _parse_bytes(self) -> bytes:
        colon = self._data.find(b":", self._idx)
        if colon == -1:
            raise ValidationError("torrent_bencode_bytes", "Torrent file has malformed byte strings.")
        raw_len = self._data[self._idx : colon]
        if not raw_len.isdigit():
            raise ValidationError("torrent_bencode_bytes", "Torrent file has malformed byte strings.")
        length = int(raw_len)
        self._idx = colon + 1
        end = self._idx + length
        if end > len(self._data):
            raise ValidationError("torrent_bencode_bytes", "Torrent file has malformed byte strings.")
        value = self._data[self._idx : end]
        self._idx = end
        return value

    def _parse_list(self) -> list[Any]:
        self._idx += 1
        result: list[Any] = []
        while True:
            if self._idx >= len(self._data):
                raise ValidationError("torrent_bencode_list", "Torrent file has malformed list fields.")
            if self._data[self._idx : self._idx + 1] == b"e":
                self._idx += 1
                return result
            result.append(self._parse_value())

    def _parse_dict(self) -> dict[bytes, Any]:
        self._idx += 1
        result: dict[bytes, Any] = {}
        while True:
            if self._idx >= len(self._data):
                raise ValidationError("torrent_bencode_dict", "Torrent file has malformed dictionary fields.")
            if self._data[self._idx : self._idx + 1] == b"e":
                self._idx += 1
                return result
            key = self._parse_bytes()
            if not isinstance(key, bytes):
                raise ValidationError("torrent_bencode_dict", "Torrent file has malformed dictionary keys.")
            result[key] = self._parse_value()


def _bencode_encode(value: Any) -> bytes:
    if isinstance(value, int):
        return b"i" + str(value).encode("ascii") + b"e"
    if isinstance(value, bytes):
        return str(len(value)).encode("ascii") + b":" + value
    if isinstance(value, list):
        return b"l" + b"".join(_bencode_encode(item) for item in value) + b"e"
    if isinstance(value, dict):
        encoded_items = []
        for key in sorted(value.keys()):
            if not isinstance(key, bytes):
                raise ValidationError("torrent_bencode_key", "Torrent file has invalid dictionary key types.")
            encoded_items.append(_bencode_encode(key))
            encoded_items.append(_bencode_encode(value[key]))
        return b"d" + b"".join(encoded_items) + b"e"
    raise ValidationError("torrent_bencode_type", "Torrent file has unsupported metadata types.")


def _as_text(value: Any, reason_code: str, user_message: str) -> str:
    if not isinstance(value, bytes):
        raise ValidationError(reason_code, user_message)
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(reason_code, user_message) from exc


def validate_magnet_url(magnet_url: str) -> MagnetValidationResult:
    if any(ord(ch) < 32 for ch in magnet_url):
        raise ValidationError("magnet_control_chars", "Magnet link has invalid control characters.")

    max_length = get_max_magnet_url_length()
    if len(magnet_url) > max_length:
        raise ValidationError("magnet_too_long", f"Magnet link is too long (>{max_length} chars).")

    try:
        parsed = urlparse(magnet_url)
    except ValueError as exc:
        raise ValidationError("magnet_parse", "Could not parse magnet URL.") from exc

    if parsed.scheme.lower() != "magnet":
        raise ValidationError("magnet_scheme", "Only magnet URLs are accepted.")

    try:
        params = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False)
    except ValueError as exc:
        raise ValidationError("magnet_parse", "Magnet URL query string is invalid.") from exc

    xt_values = params.get("xt", [])
    if not xt_values:
        raise ValidationError("magnet_xt_missing", "Magnet link is missing xt=urn:btih parameter.")

    btih_hash: str | None = None
    for candidate in xt_values:
        match = _BTih_RE.match(candidate)
        if not match:
            continue
        btih_hash = match.group(1)
        break

    if btih_hash is None:
        raise ValidationError("magnet_xt_invalid", "Magnet xt parameter must be urn:btih:<hash>.")

    if _HEX40_RE.match(btih_hash):
        normalized_infohash = btih_hash.lower()
    elif _BASE32_RE.match(btih_hash.upper()) and len(btih_hash) == 32:
        import base64

        raw = base64.b32decode(btih_hash.upper())
        normalized_infohash = raw.hex().lower()
    else:
        raise ValidationError("magnet_btih_length", "Magnet BTIH hash must be 40 hex or 32 base32 chars.")

    trackers = params.get("tr", [])
    if not trackers and not params.get("ws"):
        raise ValidationError("magnet_no_source", "Magnet link must include at least one tracker (tr) or web seed (ws).")

    max_trackers = get_max_magnet_trackers()
    if len(trackers) > max_trackers:
        raise ValidationError("magnet_trackers_exceeded", f"Magnet contains too many trackers (>{max_trackers}).")

    for key, values in params.items():
        for value in values:
            if len(value) > 2048:
                raise ValidationError("magnet_param_too_long", f"Magnet parameter '{key}' is too long.")
            if _has_invalid_percent_encoding(value):
                raise ValidationError("magnet_percent_encoding", "Magnet URL has invalid percent-encoding.")
            unquote(value)

    normalized_magnet = f"magnet:?xt=urn:btih:{normalized_infohash}"
    for tracker in trackers:
        normalized_magnet += f"&tr={tracker}"
    for web_seed in params.get("ws", []):
        normalized_magnet += f"&ws={web_seed}"

    return MagnetValidationResult(infohash=normalized_infohash, normalized_magnet=normalized_magnet)


def validate_torrent_file(file_path: Path) -> TorrentFileValidationResult:
    size_bytes = file_path.stat().st_size
    hard_limit = get_max_torrent_bytes_hard()
    if size_bytes > hard_limit:
        raise ValidationError("torrent_size_hard_limit", f"Torrent file is too large (>{hard_limit} bytes).")

    payload = file_path.read_bytes()
    decoded = _BencodeDecoder(payload).decode()
    if not isinstance(decoded, dict):
        raise ValidationError("torrent_top_level", "Torrent file must contain a top-level dictionary.")

    info = decoded.get(b"info")
    if not isinstance(info, dict):
        raise ValidationError("torrent_info_missing", "Torrent file is missing info dictionary.")

    piece_length = info.get(b"piece length")
    if not isinstance(piece_length, int) or piece_length <= 0:
        raise ValidationError("torrent_piece_length", "Torrent info.piece length must be a positive integer.")

    pieces = info.get(b"pieces")
    if not isinstance(pieces, bytes) or (len(pieces) % 20 != 0):
        raise ValidationError("torrent_pieces", "Torrent info.pieces must be bytes with length divisible by 20.")

    name_raw = info.get(b"name")
    name = _as_text(name_raw, "torrent_name", "Torrent info.name must be valid UTF-8 text.")
    if len(name) > get_max_torrent_name_length():
        raise ValidationError("torrent_name_length", "Torrent name exceeds configured maximum length.")

    announce = decoded.get(b"announce")
    if announce is not None and not isinstance(announce, bytes):
        raise ValidationError("torrent_announce_type", "Torrent announce must be a string when provided.")
    if isinstance(announce, bytes) and len(announce) > get_max_torrent_tracker_url_length():
        raise ValidationError("torrent_announce_length", "Torrent announce URL is too long.")

    announce_list = decoded.get(b"announce-list")
    if announce_list is not None:
        if not isinstance(announce_list, list):
            raise ValidationError("torrent_announce_list_type", "Torrent announce-list must be a list.")
        for tier in announce_list:
            if not isinstance(tier, list):
                raise ValidationError("torrent_announce_list_tier", "Torrent announce-list tiers must be lists.")
            for url in tier:
                if not isinstance(url, bytes):
                    raise ValidationError("torrent_announce_list_url", "Torrent announce-list URLs must be strings.")
                if len(url) > get_max_torrent_tracker_url_length():
                    raise ValidationError("torrent_announce_list_url_len", "A tracker URL exceeds configured maximum length.")

    is_single_file = isinstance(info.get(b"length"), int) and b"files" not in info
    is_multi_file = isinstance(info.get(b"files"), list)
    if not is_single_file and not is_multi_file:
        raise ValidationError(
            "torrent_layout",
            "Torrent info must define either single-file (name+length) or multi-file (name+files) layout.",
        )

    if is_single_file:
        length = info.get(b"length")
        if not isinstance(length, int) or length < 0:
            raise ValidationError("torrent_single_length", "Torrent single-file length must be a non-negative integer.")

    file_count = 0
    aggregate_size = 0
    max_segment_length = get_max_torrent_path_segment_length()
    if is_multi_file:
        files = info.get(b"files")
        assert isinstance(files, list)
        if len(files) > get_max_torrent_file_count():
            raise ValidationError("torrent_file_count", "Torrent contains too many files.")

        for file_entry in files:
            if not isinstance(file_entry, dict):
                raise ValidationError("torrent_file_entry", "Torrent file entries must be dictionaries.")

            length = file_entry.get(b"length")
            if not isinstance(length, int) or length < 0:
                raise ValidationError("torrent_file_length", "Torrent file entry length must be non-negative integer.")
            aggregate_size += length

            path_segments = file_entry.get(b"path")
            if not isinstance(path_segments, list) or not path_segments:
                raise ValidationError("torrent_file_path", "Torrent file entries must include non-empty path segments.")

            for segment_raw in path_segments:
                segment = _as_text(
                    segment_raw,
                    "torrent_path_segment_utf8",
                    "Torrent path segments must be valid UTF-8 text.",
                )
                if not segment or segment in {".", ".."}:
                    raise ValidationError("torrent_path_segment_invalid", "Torrent file paths contain invalid segments.")
                if len(segment) > max_segment_length:
                    raise ValidationError("torrent_path_segment_length", "Torrent path segment exceeds maximum length.")
                if segment.startswith("/") or segment.startswith("\\"):
                    raise ValidationError("torrent_path_absolute", "Absolute file paths are not allowed in torrent metadata.")
                if "/" in segment or "\\" in segment:
                    raise ValidationError("torrent_path_slash", "Torrent path segments must not contain path separators.")

            file_count += 1

    max_aggregate = get_max_torrent_aggregate_bytes()
    if max_aggregate > 0 and aggregate_size > max_aggregate:
        raise ValidationError("torrent_aggregate_size", "Torrent declared total size exceeds configured policy limit.")

    infohash = sha1(_bencode_encode(info)).hexdigest().lower()

    warn_limit = get_max_torrent_bytes_warn()
    if size_bytes > warn_limit:
        # caller can log this condition based on returned size
        pass

    return TorrentFileValidationResult(infohash=infohash, size_bytes=size_bytes)
