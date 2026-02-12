"""HMAC token signing helpers for expiring download links."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from app.config import Settings


class TokenError(ValueError):
    """Raised when a download token is invalid or expired."""


@dataclass(frozen=True)
class DownloadTokenPayload:
    torrent_id: str
    expires_at: int


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def _sign(data: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def create_download_token(torrent_id: str, settings: Settings, now: int | None = None) -> str:
    """Create a signed, expiring download token for a torrent identifier."""
    issued_at = int(time.time() if now is None else now)
    payload = {
        "torrent_id": torrent_id,
        "exp": issued_at + settings.download_token_ttl_seconds,
    }
    payload_segment = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature_segment = _sign(payload_segment, settings.download_token_secret)
    return f"{payload_segment}.{signature_segment}"


def parse_download_token(
    token: str,
    settings: Settings,
    now: int | None = None,
) -> DownloadTokenPayload:
    """Validate and parse a token into a payload object."""
    if "." not in token:
        raise TokenError("Malformed token")

    payload_segment, signature_segment = token.split(".", maxsplit=1)
    expected_signature = _sign(payload_segment, settings.download_token_secret)
    if not hmac.compare_digest(signature_segment, expected_signature):
        raise TokenError("Invalid token signature")

    try:
        payload = json.loads(_b64url_decode(payload_segment).decode("utf-8"))
        torrent_id = str(payload["torrent_id"])
        expires_at = int(payload["exp"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise TokenError("Malformed token payload") from exc

    current_time = int(time.time() if now is None else now)
    if current_time > expires_at:
        raise TokenError("Token expired")

    return DownloadTokenPayload(torrent_id=torrent_id, expires_at=expires_at)
