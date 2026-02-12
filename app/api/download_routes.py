"""Download route scaffold for expiring token-based links."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.security.signing import TokenError, parse_download_token


@dataclass(frozen=True)
class DownloadAccessDecision:
    allowed: bool
    status_code: int
    message: str
    torrent_id: str | None = None


def validate_download_request(token: str, settings: Settings) -> DownloadAccessDecision:
    """Validate a download token and produce a simple access decision."""
    try:
        payload = parse_download_token(token=token, settings=settings)
    except TokenError as exc:
        return DownloadAccessDecision(allowed=False, status_code=403, message=str(exc))

    return DownloadAccessDecision(
        allowed=True,
        status_code=200,
        message="Token valid",
        torrent_id=payload.torrent_id,
    )
