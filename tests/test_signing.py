from __future__ import annotations

import unittest

from app.security.signing import (
    DownloadTokenPayload,
    ExpiredTokenError,
    InvalidTokenError,
    create_download_token,
    verify_download_token,
)


class SigningTests(unittest.TestCase):
    def test_verify_valid_token(self) -> None:
        token = create_download_token(
            DownloadTokenPayload(reference="downloads/file1.iso", expires_at=2_000_000_000),
            secret="top-secret",
        )

        payload = verify_download_token(token=token, secret="top-secret", now=1_700_000_000)
        self.assertEqual(payload.reference, "downloads/file1.iso")
        self.assertEqual(payload.expires_at, 2_000_000_000)

    def test_verify_rejects_tampered_token(self) -> None:
        token = create_download_token(
            DownloadTokenPayload(reference="downloads/file1.iso", expires_at=2_000_000_000),
            secret="top-secret",
        )
        payload_part, _ = token.split(".", maxsplit=1)
        tampered = f"{payload_part}.AAAA"

        with self.assertRaises(InvalidTokenError):
            verify_download_token(token=tampered, secret="top-secret", now=1_700_000_000)

    def test_verify_rejects_expired_token(self) -> None:
        token = create_download_token(
            DownloadTokenPayload(reference="downloads/file1.iso", expires_at=100),
            secret="top-secret",
        )

        with self.assertRaises(ExpiredTokenError):
            verify_download_token(token=token, secret="top-secret", now=200)


if __name__ == "__main__":
    unittest.main()
