from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from services.image_conversation_service import ImageConversationService
from services.image_conversation_store import JSONImageConversationStore


OWNER = {"id": "owner-1", "name": "Owner", "role": "user"}
OTHER_OWNER = {"id": "owner-2", "name": "Other", "role": "user"}


class ImageConversationServiceTests(unittest.TestCase):
    def make_service(self) -> ImageConversationService:
        tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp_dir.cleanup)
        return ImageConversationService(Path(tmp_dir.name) / "image_conversations.json")

    def test_create_list_and_update_conversation(self):
        service = self.make_service()

        saved = service.upsert_conversation(OWNER, conversation_id="conv-1", title="First title")
        self.assertEqual(saved["id"], "conv-1")
        self.assertEqual(saved["ownerId"], "owner-1")
        self.assertEqual(saved["title"], "First title")

        updated = service.upsert_conversation(OWNER, conversation_id="conv-1", title="Renamed")
        self.assertEqual(updated["title"], "Renamed")

        listed = service.list_conversations(OWNER)
        self.assertEqual([item["id"] for item in listed], ["conv-1"])
        self.assertEqual(listed[0]["title"], "Renamed")

    def test_owner_isolation(self):
        service = self.make_service()
        service.upsert_conversation(OWNER, conversation_id="conv-1", title="Private")

        self.assertEqual(service.list_conversations(OTHER_OWNER), [])
        other = service.upsert_conversation(OTHER_OWNER, conversation_id="conv-1", title="Other private")
        self.assertEqual(other["ownerId"], "owner-2")
        self.assertEqual(other["title"], "Other private")
        self.assertEqual(service.list_conversations(OWNER)[0]["title"], "Private")
        self.assertEqual(service.list_conversations(OTHER_OWNER)[0]["title"], "Other private")

    def test_multiple_service_instances_preserve_each_other_conversations(self):
        tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp_dir.cleanup)
        path = Path(tmp_dir.name) / "image_conversations.json"
        first = ImageConversationService(path)
        second = ImageConversationService(path)

        first.upsert_conversation(OWNER, conversation_id="conv-1", title="First")
        second.upsert_conversation(OTHER_OWNER, conversation_id="conv-2", title="Second")

        reloaded = ImageConversationService(path)
        self.assertEqual([item["id"] for item in reloaded.list_conversations(OWNER)], ["conv-1"])
        self.assertEqual([item["id"] for item in reloaded.list_conversations(OTHER_OWNER)], ["conv-2"])

    def test_stale_service_instance_does_not_overwrite_fresher_conversation(self):
        tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp_dir.cleanup)
        path = Path(tmp_dir.name) / "image_conversations.json"
        first = ImageConversationService(path)
        first.upsert_conversation(OWNER, conversation_id="conv-1", title="v1")
        stale = ImageConversationService(path)

        first.upsert_conversation(OWNER, conversation_id="conv-1", title="v2")
        stale.upsert_conversation(OTHER_OWNER, conversation_id="conv-2", title="Other")

        reloaded = ImageConversationService(path)
        self.assertEqual(reloaded.list_conversations(OWNER)[0]["title"], "v2")
        self.assertEqual(reloaded.list_conversations(OTHER_OWNER)[0]["title"], "Other")

    def test_stale_service_instance_refreshes_same_conversation_before_mutation(self):
        tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp_dir.cleanup)
        path = Path(tmp_dir.name) / "image_conversations.json"
        first = ImageConversationService(path)
        first.upsert_conversation(OWNER, conversation_id="conv-1", title="v1")
        stale = ImageConversationService(path)

        first.create_turn(
            OWNER,
            conversation_id="conv-1",
            turn={"id": "turn-1", "prompt": "cat", "images": [{"id": "image-1", "status": "loading"}]},
        )
        stale.upsert_conversation(OWNER, conversation_id="conv-1", title="v2")

        reloaded = ImageConversationService(path)
        conversation = reloaded.list_conversations(OWNER)[0]
        self.assertEqual(conversation["title"], "v2")
        self.assertEqual([turn["id"] for turn in conversation["turns"]], ["turn-1"])

    def test_concurrent_json_writers_preserve_distinct_conversations(self):
        tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp_dir.cleanup)
        path = Path(tmp_dir.name) / "image_conversations.json"
        errors: list[BaseException] = []

        def write_conversation(index: int) -> None:
            try:
                service = ImageConversationService(path)
                service.upsert_conversation(
                    {"id": f"owner-{index}", "name": f"Owner {index}", "role": "user"},
                    conversation_id=f"conv-{index}",
                    title=f"Conversation {index}",
                )
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=write_conversation, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        if errors:
            raise errors[0]
        reloaded = ImageConversationService(path)
        for index in range(8):
            identity = {"id": f"owner-{index}", "name": f"Owner {index}", "role": "user"}
            self.assertEqual([item["id"] for item in reloaded.list_conversations(identity)], [f"conv-{index}"])

    def test_json_writer_fails_closed_when_existing_file_is_corrupt(self):
        tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp_dir.cleanup)
        path = Path(tmp_dir.name) / "image_conversations.json"
        path.write_text("{not valid json", encoding="utf-8")
        service = ImageConversationService(path)

        with self.assertRaises(Exception):
            service.upsert_conversation(OWNER, conversation_id="conv-1", title="Should not overwrite")

        self.assertEqual(path.read_text(encoding="utf-8"), "{not valid json")
        self.assertEqual(JSONImageConversationStore(path).load_conversations(), [])

    def test_create_turn_and_update_result(self):
        service = self.make_service()
        service.upsert_conversation(OWNER, conversation_id="conv-1", title="Cat")

        conversation = service.create_turn(
            OWNER,
            conversation_id="conv-1",
            turn={
                "id": "turn-1",
                "prompt": "cat",
                "model": "gpt-image-2",
                "mode": "generate",
                "referenceImages": [],
                "count": 1,
                "size": "1024x1024",
                "ratio": "1:1",
                "tier": "1k",
                "quality": "auto",
                "images": [{"id": "image-1", "taskId": "task-1", "status": "loading"}],
                "createdAt": "2026-06-21T00:00:00.000Z",
                "status": "queued",
            },
        )
        self.assertEqual(conversation["turns"][0]["id"], "turn-1")
        self.assertEqual(conversation["turns"][0]["images"][0]["taskId"], "task-1")

        updated = service.update_result(
            OWNER,
            conversation_id="conv-1",
            image_id="image-1",
            updates={"status": "success", "url": "http://api.test/images/cat.png", "revised_prompt": "cat revised"},
        )
        image = updated["turns"][0]["images"][0]
        self.assertEqual(image["status"], "success")
        self.assertEqual(image["url"], "http://api.test/images/cat.png")
        self.assertEqual(updated["turns"][0]["status"], "success")

    def test_create_turn_normalizes_invalid_count(self):
        service = self.make_service()
        service.upsert_conversation(OWNER, conversation_id="conv-1", title="Cat")

        conversation = service.create_turn(
            OWNER,
            conversation_id="conv-1",
            turn={
                "id": "turn-1",
                "prompt": "cat",
                "count": "not-a-number",
                "images": [{"id": "image-1", "status": "loading"}],
            },
        )

        self.assertEqual(conversation["turns"][0]["count"], 1)

    def test_soft_delete_conversation(self):
        service = self.make_service()
        service.upsert_conversation(OWNER, conversation_id="conv-1", title="Private")
        service.delete_conversation(OWNER, "conv-1")

        self.assertEqual(service.list_conversations(OWNER), [])


if __name__ == "__main__":
    unittest.main()
