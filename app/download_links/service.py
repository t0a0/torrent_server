"""Expiring link generation for per-user HFS folder access."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import secrets
from pathlib import Path
from urllib.parse import quote, urlencode

from .config import (
    get_download_link_secret,
    get_download_link_ttl_seconds,
    get_finished_downloads_root,
    get_hfs_base_url,
)


@dataclass(slots=True, frozen=True)
class SignedFolderLink:
    """Serialized public link payload for one user-specific folder."""

    user_id: int
    expires_at_epoch: int
    nonce: str
    signature: str


class DownloadLinkService:
    """Generates signed HFS folder links scoped to one Telegram user id."""

    def __init__(
        self,
        hfs_base_url: str | None = None,
        signing_secret: str | None = None,
        ttl_seconds: int | None = None,
        finished_downloads_root: Path | None = None,
    ) -> None:
        self._hfs_base_url = hfs_base_url if hfs_base_url is not None else get_hfs_base_url()
        self._signing_secret = (
            signing_secret if signing_secret is not None else get_download_link_secret()
        )
        self._ttl_seconds = ttl_seconds if ttl_seconds is not None else get_download_link_ttl_seconds()
        self._finished_downloads_root = (finished_downloads_root or get_finished_downloads_root()).resolve()

    def is_configured(self) -> bool:
        """Return whether public HFS base URL is configured."""
        return bool(self._hfs_base_url)

    def build_user_folder_link(self, user_id: int) -> str:
        """Return an expiring signed link that always points to `/.../<user_id>/`."""
        if not self._hfs_base_url:
            raise ValueError("HFS_BASE_URL is not configured")

        signed_payload = self._build_signed_payload(user_id=user_id)
        query = urlencode(
            {
                "expires": signed_payload.expires_at_epoch,
                "nonce": signed_payload.nonce,
                "sig": signed_payload.signature,
            }
        )
        return f"{self._hfs_base_url}/{user_id}/?{query}"

    def build_user_content_link(self, user_id: int, content_path: Path) -> str:
        """Return an expiring signed link to one completed file/folder under user root."""
        if not self._hfs_base_url:
            raise ValueError("HFS_BASE_URL is not configured")

        user_root = self.resolve_user_folder(user_id)
        resolved_content_path = content_path.resolve()
        if resolved_content_path != user_root and user_root not in resolved_content_path.parents:
            raise ValueError("Content path is outside of user folder")

        relative_parts = resolved_content_path.relative_to(user_root).parts
        encoded_relative_path = "/".join(quote(part, safe="") for part in relative_parts)
        suffix = f"/{encoded_relative_path}" if encoded_relative_path else "/"

        signed_payload = self._build_signed_payload(user_id=user_id)
        query = urlencode(
            {
                "expires": signed_payload.expires_at_epoch,
                "nonce": signed_payload.nonce,
                "sig": signed_payload.signature,
            }
        )
        return f"{self._hfs_base_url}/{user_id}{suffix}?{query}"

    def resolve_user_folder(self, user_id: int) -> Path:
        """Resolve and return the only permitted folder for a Telegram user id."""
        user_root = (self._finished_downloads_root / str(user_id)).resolve()
        if self._finished_downloads_root not in user_root.parents and user_root != self._finished_downloads_root:
            raise ValueError("Resolved user folder is outside of downloads root")
        return user_root

    def verify_folder_link(self, user_id: int, expires: int, nonce: str, signature: str) -> bool:
        """Validate expiring signature for user folder access."""
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        if expires <= now_epoch:
            return False

        expected = self._build_signature(user_id=user_id, expires=expires, nonce=nonce)
        return hmac.compare_digest(expected, signature)

    def _build_signed_payload(self, user_id: int) -> SignedFolderLink:
        expires = int((datetime.now(timezone.utc) + timedelta(seconds=self._ttl_seconds)).timestamp())
        nonce = base64.urlsafe_b64encode(secrets.token_bytes(18)).decode("ascii").rstrip("=")
        signature = self._build_signature(user_id=user_id, expires=expires, nonce=nonce)
        return SignedFolderLink(
            user_id=user_id,
            expires_at_epoch=expires,
            nonce=nonce,
            signature=signature,
        )

    def _build_signature(self, user_id: int, expires: int, nonce: str) -> str:
        uri = f"/{user_id}/"
        payload = f"{expires}{uri}{nonce} {self._signing_secret}".encode("utf-8")
        digest = hashlib.md5(payload).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
