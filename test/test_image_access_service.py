from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

from services import image_access_service


class ImageAccessServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        fake_config = SimpleNamespace(
            session_secret="session-secret",
            data={"image_access_token_ttl_seconds": 60},
        )
        patcher = mock.patch.object(image_access_service, "config", fake_config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_append_and_verify_image_access_token(self) -> None:
        url = image_access_service.append_image_access_token("https://app.test/images/a.png", "a.png")

        self.assertIn("image_token=", url)
        token = url.split("image_token=", 1)[1]
        image_access_service.verify_image_access_token("a.png", token)

    def test_rejects_token_for_different_path(self) -> None:
        token = image_access_service.create_image_access_token("a.png")

        with self.assertRaises(HTTPException) as ctx:
            image_access_service.verify_image_access_token("b.png", token)

        self.assertEqual(ctx.exception.status_code, 401)

    def test_rejects_expired_token(self) -> None:
        token = image_access_service.create_image_access_token("a.png", now=1)

        with self.assertRaises(HTTPException) as ctx:
            image_access_service.verify_image_access_token("a.png", token)

        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
