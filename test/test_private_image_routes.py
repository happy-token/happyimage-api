from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from services.image_access_service import create_image_access_token


def png_bytes() -> bytes:
    path = Path(tempfile.gettempdir()) / "HappyImage-private-route-test.png"
    Image.new("RGB", (2, 2), color=(0, 128, 255)).save(path, format="PNG")
    return path.read_bytes()


class PrivateImageRouteTests(unittest.TestCase):
    def test_images_require_signed_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "images"
            rel = "2026/06/19/private.png"
            image_path = root / rel
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(png_bytes())
            fake_config = SimpleNamespace(
                images_dir=root,
                image_thumbnails_dir=Path(tmp) / "image_thumbnails",
                session_secret="session-secret",
                auth_key="auth-key",
                data={"image_access_token_ttl_seconds": 60},
                cleanup_old_images=lambda: 0,
            )

            with ExitStack() as stack:
                stack.enter_context(mock.patch("services.image_service.config", fake_config))
                stack.enter_context(mock.patch("services.image_storage_service.config", fake_config))
                stack.enter_context(mock.patch("services.image_access_service.config", fake_config))
                token = create_image_access_token(rel)
                with TestClient(create_app()) as client:
                    missing = client.get(f"/images/{rel}")
                    allowed = client.get(f"/images/{rel}?image_token={token}")

            self.assertEqual(missing.status_code, 401)
            self.assertEqual(allowed.status_code, 200)
            self.assertEqual(allowed.headers.get("content-type"), "image/png")


if __name__ == "__main__":
    unittest.main()
