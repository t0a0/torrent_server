"""Download route skeleton for expiring token-based links."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.security.signing import ExpiredTokenError, InvalidTokenError, verify_download_token


@dataclass(frozen=True)
class DownloadRouteResult:
    """Minimal route result abstraction for future framework integration."""

    status_code: int
    body: str
    file_path: Path | None = None


def handle_download_request(
    token: str,
    secret: str,
    base_download_dir: Path,
) -> DownloadRouteResult:
    """Validate token and return a response-like structure.

    Status codes:
    - 403 for invalid/tampered tokens.
    - 410 for expired tokens.
    - 404 when token is valid but file is missing.
    - 200 when token is valid and file exists.
    """
    try:
        payload = verify_download_token(token=token, secret=secret)
    except InvalidTokenError:
        return DownloadRouteResult(status_code=403, body="Invalid download token")
    except ExpiredTokenError:
        return DownloadRouteResult(status_code=410, body="Download token expired")

    resolved_path = (base_download_dir / payload.reference).resolve()
    base_path = base_download_dir.resolve()
    if base_path not in resolved_path.parents and resolved_path != base_path:
        return DownloadRouteResult(status_code=403, body="Invalid file reference")

    if not resolved_path.exists() or not resolved_path.is_file():
        return DownloadRouteResult(status_code=404, body="File not found")

    return DownloadRouteResult(status_code=200, body="OK", file_path=resolved_path)
