from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from services.share_draft_service import ShareDraftService


OWNER = {"id": "owner-1", "name": "Owner"}
OTHER_OWNER = {"id": "owner-2", "name": "Other"}


def make_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "source": "ignored",
        "image_url": "/images/cat.png",
        "conversation_id": "conv-1",
        "turn_id": "turn-1",
        "image_id": "image-1",
        "original_prompt": "a cat wearing a tiny hat",
        "conversation_summary": "cat design",
        "share_prompt": "make a cat poster",
        "title": "Cat poster",
        "category": " poster ",
        "tags": [" cat ", "", "poster", "  "],
        "status": "draft",
    }
    payload.update(overrides)
    return payload


class ShareDraftServiceTests(unittest.TestCase):
    def test_save_and_list_drafts_are_scoped_by_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ShareDraftService(Path(tmp_dir) / "share_drafts.json")
            first = service.save_draft(OWNER, make_payload(id="draft-1", image_id="image-1"))
            time.sleep(0.01)
            second = service.save_draft(OWNER, make_payload(id="draft-2", image_id="image-2", title="Newer draft"))
            service.save_draft(OTHER_OWNER, make_payload(id="draft-1", title="Other owner draft"))

            owner_items = service.list_drafts(OWNER)["items"]
            other_items = service.list_drafts(OTHER_OWNER)["items"]

            self.assertEqual(first["owner_id"], "owner-1")
            self.assertEqual(second["owner_id"], "owner-1")
            self.assertEqual([item["id"] for item in owner_items], ["draft-2", "draft-1"])
            self.assertEqual(len(other_items), 1)
            self.assertEqual(other_items[0]["owner_id"], "owner-2")

    def test_save_updates_existing_owner_draft_instead_of_duplicating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ShareDraftService(Path(tmp_dir) / "share_drafts.json")
            first = service.save_draft(OWNER, make_payload(id="draft-1", title="Cat poster"))
            time.sleep(0.01)
            second = service.save_draft(
                OWNER,
                make_payload(
                    id="draft-1",
                    title="Updated cat poster",
                    category="  featured  ",
                    tags=[" cat ", None, "featured", ""],
                    status="approved",
                ),
            )

            items = service.list_drafts(OWNER)["items"]

            self.assertEqual(second["id"], "draft-1")
            self.assertEqual(second["title"], "Updated cat poster")
            self.assertEqual(second["category"], "featured")
            self.assertEqual(second["tags"], ["cat", "featured"])
            self.assertEqual(second["status"], "approved")
            self.assertEqual(second["created_at"], first["created_at"])
            self.assertGreater(second["updated_at"], first["updated_at"])
            self.assertEqual(len(items), 1)

    def test_save_without_id_updates_existing_owner_image_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ShareDraftService(Path(tmp_dir) / "share_drafts.json")
            first = service.save_draft(OWNER, make_payload(id="draft-1", title="Cat poster", image_id="image-1"))
            time.sleep(0.01)
            second = service.save_draft(
                OWNER,
                make_payload(title="Updated from image", image_id="image-1"),
            )

            items = service.list_drafts(OWNER)["items"]

            self.assertEqual(second["id"], "draft-1")
            self.assertEqual(second["title"], "Updated from image")
            self.assertEqual(second["created_at"], first["created_at"])
            self.assertEqual(len(items), 1)

    def test_explicit_different_id_with_same_image_creates_separate_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ShareDraftService(Path(tmp_dir) / "share_drafts.json")
            original = service.save_draft(OWNER, make_payload(id="draft-1", title="Original", image_id="image-1"))
            time.sleep(0.01)
            duplicate_image = service.save_draft(
                OWNER,
                make_payload(id="draft-2", title="Distinct draft", image_id="image-1"),
            )

            items = service.list_drafts(OWNER)["items"]

            self.assertEqual(original["id"], "draft-1")
            self.assertEqual(duplicate_image["id"], "draft-2")
            self.assertEqual({item["id"] for item in items}, {"draft-1", "draft-2"})
            self.assertEqual(len(items), 2)

    def test_invalid_status_defaults_to_draft_and_missing_required_field_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ShareDraftService(Path(tmp_dir) / "share_drafts.json")

            item = service.save_draft(OWNER, make_payload(status="nonsense"))
            anonymous_item = service.save_draft({}, make_payload(id="anonymous-draft", image_id="anonymous-image"))

            self.assertEqual(item["status"], "draft")
            self.assertEqual(item["source"], "user_gallery")
            self.assertEqual(anonymous_item["owner_id"], "anonymous")
            with self.assertRaises(ValueError):
                service.save_draft(OWNER, make_payload(image_url=""))

    def test_new_service_instance_loads_persisted_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "share_drafts.json"
            service = ShareDraftService(path)
            saved = service.save_draft(OWNER, make_payload(id="draft-1", title="Persisted"))

            reloaded = ShareDraftService(path)
            items = reloaded.list_drafts(OWNER)["items"]

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["id"], saved["id"])
            self.assertEqual(items[0]["title"], "Persisted")
            self.assertEqual(items[0]["owner_id"], "owner-1")


if __name__ == "__main__":
    unittest.main()
