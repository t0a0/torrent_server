"""Validation gates for torrent files and magnet URLs."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import re
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

_INVALID_PERCENT_ENCODING = re.compile(r"%(?![0-9A-Fa-f]{2})")
_BTih_PREFIX = "urn:btih:"


class ValidationError(ValueError):
    """Raised when user input fails validation with a stable user-facing message."""

    def __init__(self, code: str, user_message: str) -> None:
        super().__init__(code)
        self.code = code
        self.user_message = user_message


@dataclass(frozen=True)
class TorrentValidationResult:
    infohash: str


@dataclass(frozen=True)
class MagnetValidationResult:
    infohash: str
    normalized_url: str


class _BencodeParser:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._index = 0

    def parse(self) -> Any:
        value = self._parse_value()
        if self._index != len(self._data):
            raise ValidationError("bencode_trailing_data", "Invalid .torrent file structure.")
        return value

    def _parse_value(self) -> Any:
        if self._index >= len(self._data):
            raise ValidationError("bencode_unexpected_eof", "Invalid .torrent file structure.")

        token = self._data[self._index : self._index + 1]
        if token == b"i":
            return self._parse_int()
        if token == b"l":
            return self._parse_list()
        if token == b"d":
            return self._parse_dict()
        if token.isdigit():
            return self._parse_bytes()
        raise ValidationError("bencode_bad_token", "Invalid .torrent file structure.")

    def _parse_int(self) -> int:
        self._index += 1
        end_index = self._data.find(b"e", self._index)
        if end_index == -1:
            raise ValidationError("bencode_bad_int", "Invalid .torrent integer field.")
        raw = self._data[self._index:end_index]
        self._index = end_index + 1
        if not raw or (raw.startswith(b"0") and raw != b"0") or raw == b"-0":
            raise ValidationError("bencode_bad_int", "Invalid .torrent integer field.")
        try:
            return int(raw)
        except ValueError as exc:
            raise ValidationError("bencode_bad_int", "Invalid .torrent integer field.") from exc

    def _parse_list(self) -> list[Any]:
        self._index += 1
        output: list[Any] = []
        while True:
            if self._index >= len(self._data):
                raise ValidationError("bencode_bad_list", "Invalid .torrent list field.")
            if self._data[self._index : self._index + 1] == b"e":
                self._index += 1
                return output
            output.append(self._parse_value())

    def _parse_dict(self) -> dict[bytes, Any]:
        self._index += 1
        output: dict[bytes, Any] = {}
        prev_key: bytes | None = None
        while True:
            if self._index >= len(self._data):
                raise ValidationError("bencode_bad_dict", "Invalid .torrent dictionary field.")
            if self._data[self._index : self._index + 1] == b"e":
                self._index += 1
                return output
            key = self._parse_bytes()
            if prev_key is not None and key < prev_key:
                raise ValidationError("bencode_unsorted_dict", "Invalid .torrent dictionary ordering.")
            prev_key = key
            output[key] = self._parse_value()

    def _parse_bytes(self) -> bytes:
        colon_index = self._data.find(b":", self._index)
        if colon_index == -1:
            raise ValidationError("bencode_bad_bytes", "Invalid .torrent byte string field.")
        raw_len = self._data[self._index:colon_index]
        if not raw_len or not raw_len.isdigit():
            raise ValidationError("bencode_bad_bytes", "Invalid .torrent byte string field.")
        length = int(raw_len)
        self._index = colon_index + 1
        end = self._index + length
        if end > len(self._data):
            raise ValidationError("bencode_bad_bytes", "Invalid .torrent byte string field.")
        out = self._data[self._index:end]
        self._index = end
        return out


def _bencode_encode(value: Any) -> bytes:
    if isinstance(value, int):
        return b"i" + str(value).encode("ascii") + b"e"
    if isinstance(value, bytes):
        return str(len(value)).encode("ascii") + b":" + value
    if isinstance(value, list):
        return b"l" + b"".join(_bencode_encode(item) for item in value) + b"e"
    if isinstance(value, dict):
        if not all(isinstance(key, bytes) for key in value):
            raise ValidationError("bencode_bad_dict_key", "Invalid .torrent metadata structure.")
        items = sorted(value.items(), key=lambda item: item[0])
        return b"d" + b"".join(_bencode_encode(k) + _bencode_encode(v) for k, v in items) + b"e"
    raise ValidationError("bencode_unknown_type", "Invalid .torrent metadata structure.")


def _as_text(value: Any, code: str, user_message: str) -> str:
    if not isinstance(value, bytes):
        raise ValidationError(code, user_message)
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(code, user_message) from exc


def validate_torrent_file_bytes(
    *,
    torrent_bytes: bytes,
    max_torrent_name_length: int,
    max_tracker_url_length: int,
    max_path_segment_length: int,
    max_torrent_file_count: int,
    max_torrent_aggregate_size_bytes: int,
) -> TorrentValidationResult:
    parsed = _BencodeParser(torrent_bytes).parse()
    if not isinstance(parsed, dict):
        raise ValidationError("torrent_not_dict", "Invalid .torrent file: top-level dictionary required.")

    info = parsed.get(b"info")
    if not isinstance(info, dict):
        raise ValidationError("torrent_missing_info", "Invalid .torrent file: missing info dictionary.")

    piece_length = info.get(b"piece length")
    if not isinstance(piece_length, int) or piece_length <= 0:
        raise ValidationError("torrent_bad_piece_length", "Invalid .torrent file: bad piece length.")

    pieces = info.get(b"pieces")
    if not isinstance(pieces, bytes) or len(pieces) == 0 or (len(pieces) % 20 != 0):
        raise ValidationError("torrent_bad_pieces", "Invalid .torrent file: bad pieces metadata.")

    name = _as_text(info.get(b"name"), "torrent_bad_name", "Invalid .torrent file: missing name.")
    if len(name) > max_torrent_name_length:
        raise ValidationError("torrent_name_too_long", "Torrent name is too long.")

    _validate_tracker_fields(parsed, max_tracker_url_length)

    files = info.get(b"files")
    if files is None:
        length = info.get(b"length")
        if not isinstance(length, int) or length < 0:
            raise ValidationError("torrent_bad_single_file", "Invalid .torrent file: bad single-file metadata.")
    else:
        if not isinstance(files, list) or not files:
            raise ValidationError("torrent_bad_files", "Invalid .torrent file: bad files list.")
        if len(files) > max_torrent_file_count:
            raise ValidationError("torrent_too_many_files", "Torrent contains too many files.")

        aggregate_size = 0
        for entry in files:
            if not isinstance(entry, dict):
                raise ValidationError("torrent_bad_file_entry", "Invalid .torrent file: bad file entry.")
            length = entry.get(b"length")
            if not isinstance(length, int) or length < 0:
                raise ValidationError("torrent_bad_file_length", "Invalid .torrent file: bad file length.")
            aggregate_size += length

            path = entry.get(b"path")
            if not isinstance(path, list) or not path:
                raise ValidationError("torrent_bad_path", "Invalid .torrent file: bad file path.")

            for part in path:
                segment = _as_text(part, "torrent_bad_path_segment", "Invalid .torrent file: bad path segment.")
                if not segment or segment in {".", ".."}:
                    raise ValidationError("torrent_bad_path_segment", "Invalid .torrent file path segment.")
                if segment.startswith("/") or segment.startswith("\\"):
                    raise ValidationError("torrent_absolute_path", "Absolute paths are not allowed in .torrent files.")
                if len(segment) > max_path_segment_length:
                    raise ValidationError("torrent_path_segment_too_long", "A torrent path segment is too long.")
                if "/" in segment or "\\" in segment:
                    raise ValidationError("torrent_bad_path_segment", "Invalid .torrent file path segment.")

        if max_torrent_aggregate_size_bytes > 0 and aggregate_size > max_torrent_aggregate_size_bytes:
            raise ValidationError("torrent_aggregate_too_large", "Torrent declared content size exceeds policy limit.")

    infohash = hashlib.sha1(_bencode_encode(info)).hexdigest().lower()
    return TorrentValidationResult(infohash=infohash)


def _validate_tracker_fields(parsed: dict[bytes, Any], max_tracker_url_length: int) -> None:
    announce = parsed.get(b"announce")
    if announce is not None:
        announce_text = _as_text(
            announce,
            "torrent_bad_announce",
            "Invalid .torrent file: bad announce URL.",
        )
        if len(announce_text) > max_tracker_url_length:
            raise ValidationError("torrent_tracker_too_long", "Tracker URL is too long.")

    announce_list = parsed.get(b"announce-list")
    if announce_list is None:
        return
    if not isinstance(announce_list, list):
        raise ValidationError("torrent_bad_announce_list", "Invalid .torrent file: bad announce-list.")

    for tier in announce_list:
        if not isinstance(tier, list):
            raise ValidationError("torrent_bad_announce_list", "Invalid .torrent file: bad announce-list.")
        for tracker in tier:
            tracker_text = _as_text(
                tracker,
                "torrent_bad_announce_list",
                "Invalid .torrent file: bad announce-list tracker URL.",
            )
            if len(tracker_text) > max_tracker_url_length:
                raise ValidationError("torrent_tracker_too_long", "Tracker URL is too long.")


def validate_magnet_url(
    *,
    magnet_url: str,
    max_url_length: int,
    max_trackers: int,
    max_param_length: int,
    require_source_param: bool,
) -> MagnetValidationResult:
    raw = magnet_url.strip()
    if not raw:
        raise ValidationError("magnet_empty", "Please send a magnet URL or upload a .torrent file.")
    if len(raw) > max_url_length:
        raise ValidationError("magnet_too_long", "Magnet URL is too long.")
    if any(ord(ch) < 32 for ch in raw):
        raise ValidationError("magnet_control_chars", "Magnet URL contains invalid control characters.")
    if _INVALID_PERCENT_ENCODING.search(raw):
        raise ValidationError("magnet_percent_encoding", "Magnet URL contains invalid percent-encoding.")

    parsed = urlsplit(raw)
    if parsed.scheme.lower() != "magnet":
        raise ValidationError("magnet_bad_scheme", "Only magnet URLs are accepted here.")

    params = parse_qsl(parsed.query, keep_blank_values=True)
    xt_values = [value for key, value in params if key == "xt"]
    if not xt_values:
        raise ValidationError("magnet_missing_xt", "Magnet URL must include xt=urn:btih:<hash>.")

    infohash = _extract_infohash(xt_values)

    tracker_count = 0
    has_source = False
    normalized_pairs: list[tuple[str, str]] = [("xt", f"urn:btih:{infohash}")]
    for key, value in params:
        if len(key) > max_param_length or len(value) > max_param_length:
            raise ValidationError("magnet_param_too_long", "A magnet parameter is too long.")
        if key == "xt":
            continue
        if key == "tr":
            tracker_count += 1
            has_source = True
            if tracker_count > max_trackers:
                raise ValidationError("magnet_too_many_trackers", "Too many tracker parameters in magnet URL.")
        if key == "ws":
            has_source = True
        normalized_pairs.append((key, value))

    if require_source_param and not has_source:
        raise ValidationError("magnet_missing_source", "Magnet URL must include at least one tracker/web-seed parameter.")

    query = "&".join(f"{quote(key, safe='')}={quote(value, safe=':/?&=+%')}" for key, value in normalized_pairs)
    normalized_url = urlunsplit(("magnet", "", "", query, ""))
    return MagnetValidationResult(infohash=infohash, normalized_url=normalized_url)


def _extract_infohash(xt_values: list[str]) -> str:
    for xt in xt_values:
        xt_lower = xt.lower()
        if not xt_lower.startswith(_BTih_PREFIX):
            continue

        value = xt[len(_BTih_PREFIX) :]
        if len(value) == 40 and all(ch in "0123456789abcdefABCDEF" for ch in value):
            return value.lower()
        if len(value) == 32:
            try:
                decoded = base64.b32decode(value.upper())
            except Exception:
                continue
            if len(decoded) == 20:
                return decoded.hex()

    raise ValidationError("magnet_bad_btih", "Magnet URL has invalid btih hash.")
