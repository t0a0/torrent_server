from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.api.download_routes import handle_download_request
from app.security.signing import DownloadTokenPayload, create_download_token


class DownloadRouteTests(unittest.TestCase):
    def test_invalid_token_returns_403(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = handle_download_request(
                token="bad-token",
                secret="test-secret",
                base_download_dir=Path(tmp_dir),
            )

        self.assertEqual(result.status_code, 403)

    def test_expired_token_returns_410(self) -> None:
        token = create_download_token(
            DownloadTokenPayload(reference="artifact.bin", expires_at=1),
            secret="test-secret",
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = handle_download_request(
                token=token,
                secret="test-secret",
                base_download_dir=Path(tmp_dir),
            )

        self.assertEqual(result.status_code, 410)

    def test_existing_file_returns_200(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            file_path = base_dir / "artifact.bin"
            file_path.write_text("hello", encoding="utf-8")
            token = create_download_token(
                DownloadTokenPayload(reference="artifact.bin", expires_at=2_000_000_000),
                secret="test-secret",
            )

            result = handle_download_request(
                token=token,
                secret="test-secret",
                base_download_dir=base_dir,
            )

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.file_path, file_path)


if __name__ == "__main__":
    unittest.main()
