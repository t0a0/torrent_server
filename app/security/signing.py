"""Token signing helpers for expiring download links."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass


class InvalidTokenError(ValueError):
    """Raised when a token is malformed or has an invalid signature."""


class ExpiredTokenError(ValueError):
    """Raised when a token is valid but past its expiry time."""


@dataclass(frozen=True)
class DownloadTokenPayload:
    """Structured payload embedded in a download token."""

    reference: str
    expires_at: int


def _urlsafe_b64encode(raw_bytes: bytes) -> str:
    return base64.urlsafe_b64encode(raw_bytes).decode("utf-8").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _serialize_payload(payload: DownloadTokenPayload) -> bytes:
    payload_dict = {"exp": payload.expires_at, "ref": payload.reference}
    return json.dumps(payload_dict, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _sign_payload(payload_bytes: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), payload_bytes, digestmod=hashlib.sha256).digest()


def create_download_token(payload: DownloadTokenPayload, secret: str) -> str:
    """Create a signed token from a payload using HMAC-SHA256."""
    payload_bytes = _serialize_payload(payload)
    payload_part = _urlsafe_b64encode(payload_bytes)
    signature_part = _urlsafe_b64encode(_sign_payload(payload_bytes, secret))
    return f"{payload_part}.{signature_part}"


def issue_download_token(
    reference: str,
    ttl_seconds: int,
    secret: str,
    now: int | None = None,
) -> str:
    """Issue a token for a file reference with an absolute expiration timestamp."""
    issued_at = int(time.time()) if now is None else now
    payload = DownloadTokenPayload(reference=reference, expires_at=issued_at + ttl_seconds)
    return create_download_token(payload=payload, secret=secret)


def verify_download_token(token: str, secret: str, now: int | None = None) -> DownloadTokenPayload:
    """Validate token shape, signature, and expiry.

    Raises:
        InvalidTokenError: Token malformed or signature mismatch.
        ExpiredTokenError: Token is well-formed and signed but expired.
    """
    try:
        payload_part, signature_part = token.split(".", maxsplit=1)
    except ValueError as exc:
        raise InvalidTokenError("Token format is invalid") from exc

    try:
        payload_bytes = _urlsafe_b64decode(payload_part)
        provided_signature = _urlsafe_b64decode(signature_part)
    except ValueError as exc:
        raise InvalidTokenError("Token encoding is invalid") from exc

    expected_signature = _sign_payload(payload_bytes, secret)
    if not hmac.compare_digest(provided_signature, expected_signature):
        raise InvalidTokenError("Token signature is invalid")

    try:
        payload_dict = json.loads(payload_bytes.decode("utf-8"))
        payload = DownloadTokenPayload(
            reference=str(payload_dict["ref"]),
            expires_at=int(payload_dict["exp"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InvalidTokenError("Token payload is invalid") from exc

    current_time = int(time.time()) if now is None else now
    if payload.expires_at < current_time:
        raise ExpiredTokenError("Token has expired")

    return payload
