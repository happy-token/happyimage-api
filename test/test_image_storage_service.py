from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

from services import image_service
from services.config import config
from services.image_storage_service import ImageStorageService


def png_bytes() -> bytes:
    path = Path(tempfile.gettempdir()) / "Happy Token-test-image.png"
    Image.new("RGB", (2, 2), color=(255, 0, 0)).save(path, format="PNG")
    return path.read_bytes()


class FakeWebDAVClient:
    uploaded: dict[str, bytes] = {}
    deleted: list[str] = []

    def __init__(self, _settings):
        pass

    def put(self, rel: str, payload: bytes) -> str:
        self.uploaded[rel] = payload
        return f"https://dav.example.test/{rel}"

    def get(self, rel: str) -> bytes:
        return self.uploaded[rel]

    def delete(self, rel: str) -> bool:
        self.deleted.append(rel)
        self.uploaded.pop(rel, None)
        return True

    def test(self) -> dict[str, object]:
        self.put(".happytoken_webdav_test.txt", b"happytoken webdav test\n")
        self.delete(".happytoken_webdav_test.txt")
        return {"ok": True, "status": 200, "error": None}


class ImageStorageServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.images_dir = self.data_dir / "images"
        self.settings = {
            "enabled": False,
            "mode": "local",
            "webdav_url": "",
            "webdav_username": "",
            "webdav_password": "",
            "webdav_root_path": "Happy Token/images",
            "public_base_url": "",
        }
        self.config_patcher = mock.patch("services.image_storage_service.config")
        self.mock_config = self.config_patcher.start()
        self.addCleanup(self.config_patcher.stop)
        self.mock_config.images_dir = self.images_dir
        self.mock_config.base_url = "http://app.test"
        self.mock_config.cleanup_old_images.return_value = 0
        self.mock_config.get_image_storage_settings.side_effect = lambda: dict(self.settings)
        FakeWebDAVClient.uploaded = {}
        FakeWebDAVClient.deleted = []

    def service(self) -> ImageStorageService:
        return ImageStorageService(self.data_dir / "image_index.json")

    def test_local_mode_saves_to_local_directory(self):
        with mock.patch.dict(config.data, {"session_secret": "image-test-secret"}, clear=False):
            stored = self.service().save(png_bytes(), "http://app.test", owner_id="owner-1")

        self.assertEqual(stored.storage, "local")
        self.assertTrue((self.images_dir / stored.rel).is_file())
        self.assertTrue(stored.url.startswith(f"http://app.test/images/{stored.rel}?"))
        self.assertIn("image_token=", stored.url)
        items = self.service().list_items("http://app.test", owner_id="owner-1")
        self.assertEqual(items[0]["owner_id"], "owner-1")

    def test_webdav_mode_uploads_without_local_file(self):
        self.settings.update({
            "enabled": True,
            "mode": "webdav",
            "webdav_url": "https://dav.example.test",
            "webdav_password": "secret",
        })
        with mock.patch("services.image_storage_service.WebDAVClient", FakeWebDAVClient):
            stored = self.service().save(png_bytes(), "http://app.test")
            payload = self.service().get_bytes(stored.rel)

        self.assertEqual(stored.storage, "webdav")
        self.assertFalse((self.images_dir / stored.rel).exists())
        self.assertIn(stored.rel, FakeWebDAVClient.uploaded)
        self.assertEqual(payload, FakeWebDAVClient.uploaded[stored.rel])

    def test_list_items_ignores_non_image_files(self):
        image = png_bytes()
        image_path = self.images_dir / "2026" / "05" / "07" / "sample.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(image)
        (self.images_dir / ".DS_Store").write_text("not an image", encoding="utf-8")
        (self.images_dir / "2026" / ".DS_Store").write_text("not an image", encoding="utf-8")

        items = self.service().list_items("http://app.test")

        self.assertEqual([item["rel"] for item in items], ["2026/05/07/sample.png"])
        self.assertEqual(items[0]["storage"], "local")

    def test_list_items_filters_by_owner(self):
        image = png_bytes()
        service = self.service()
        first = self.images_dir / "2026" / "05" / "07" / "owner-1.png"
        second = self.images_dir / "2026" / "05" / "07" / "owner-2.png"
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_bytes(image)
        second.write_bytes(image)
        service._save_index({
            "2026/05/07/owner-1.png": {
                "rel": "2026/05/07/owner-1.png",
                "path": "2026/05/07/owner-1.png",
                "name": "owner-1.png",
                "date": "2026-05-07",
                "created_at": "2026-05-07 00:00:01",
                "storage": "local",
                "local": True,
                "webdav": False,
                "owner_id": "owner-1",
            },
            "2026/05/07/owner-2.png": {
                "rel": "2026/05/07/owner-2.png",
                "path": "2026/05/07/owner-2.png",
                "name": "owner-2.png",
                "date": "2026-05-07",
                "created_at": "2026-05-07 00:00:02",
                "storage": "local",
                "local": True,
                "webdav": False,
                "owner_id": "owner-2",
            },
        })

        owner_items = service.list_items("http://app.test", owner_id="owner-1")
        all_items = service.list_items("http://app.test", owner_id="owner-1", include_all=True)

        self.assertEqual([item["rel"] for item in owner_items], ["2026/05/07/owner-1.png"])
        self.assertEqual(
            [item["rel"] for item in all_items],
            ["2026/05/07/owner-2.png", "2026/05/07/owner-1.png"],
        )

    def test_both_mode_saves_to_local_and_webdav(self):
        self.settings.update({
            "enabled": True,
            "mode": "both",
            "webdav_url": "https://dav.example.test",
            "webdav_password": "secret",
            "public_base_url": "https://cdn.example.test/images",
        })
        with mock.patch("services.image_storage_service.WebDAVClient", FakeWebDAVClient):
            stored = self.service().save(png_bytes(), "http://app.test")

        self.assertEqual(stored.storage, "both")
        self.assertTrue((self.images_dir / stored.rel).is_file())
        self.assertIn(stored.rel, FakeWebDAVClient.uploaded)
        self.assertEqual(stored.url, f"https://cdn.example.test/images/{stored.rel}")

    def test_test_webdav_writes_and_deletes_probe_file(self):
        self.settings.update({
            "enabled": True,
            "mode": "webdav",
            "webdav_url": "https://dav.example.test",
            "webdav_password": "secret",
        })
        with mock.patch("services.image_storage_service.WebDAVClient", FakeWebDAVClient):
            result = self.service().test_webdav()

        self.assertTrue(result["ok"])
        self.assertIn(".happytoken_webdav_test.txt", FakeWebDAVClient.deleted)

    def test_download_zip_includes_remote_only_images(self):
        rel = "2026/06/19/remote.png"
        payload = png_bytes()

        with (
            mock.patch("services.image_service.config") as mock_config,
            mock.patch("services.image_service.image_storage_service") as mock_storage,
        ):
            mock_config.images_dir = self.images_dir
            mock_storage.get_bytes.return_value = payload

            buf = image_service.download_images_zip([rel])

        with zipfile.ZipFile(buf) as archive:
            self.assertEqual(archive.namelist(), ["remote.png"])
            self.assertEqual(archive.read("remote.png"), payload)
        mock_storage.get_bytes.assert_called_once_with(rel)


if __name__ == "__main__":
    unittest.main()
