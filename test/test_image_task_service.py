from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from services.image_task_store import DatabaseImageTaskStore
from services.image_task_service import ImageTaskService


OWNER = {"id": "owner-1", "name": "Owner", "role": "admin"}
OTHER_OWNER = {"id": "owner-2", "name": "Other", "role": "user"}


def wait_for_task(service: ImageTaskService, identity: dict[str, object], task_id: str, status: str, timeout: float = 2.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        result = service.list_tasks(identity, [task_id])
        last = (result.get("items") or [None])[0]
        if last and last.get("status") == status:
            return last
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not reach {status}, last={last}")


class ImageTaskServiceTests(unittest.TestCase):
    def make_service(
        self,
        path: Path | None = None,
        handler=None,
        generation_handler=None,
        edit_handler=None,
    ) -> ImageTaskService:
        if path is None:
            tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            self.addCleanup(tmp_dir.cleanup)
            path = Path(tmp_dir.name) / "image_tasks.json"
        return ImageTaskService(
            path,
            generation_handler=generation_handler
            or handler
            or (lambda _payload: {"data": [{"url": "http://example.test/image.png"}]}),
            edit_handler=edit_handler
            or handler
            or (lambda _payload: {"data": [{"url": "http://example.test/edit.png"}]}),
            retention_days_getter=lambda: 30,
        )

    def test_submit_generation_returns_prompt_and_client_task_metadata(self):
        identity = {"id": "user-1", "role": "admin", "image_quota": 10}

        def handler(_payload):
            time.sleep(0.05)
            return {
                "data": [{"url": "http://example.test/image.png"}],
                "usage": {"total_tokens": 1},
            }

        service = self.make_service(generation_handler=handler)

        task = service.submit_generation(
            identity,
            client_task_id="client-001",
            prompt="a clean product photo",
            model="gpt-image-2",
            size="1024x1024",
            quality="auto",
            base_url="http://api.test",
        )

        assert task["id"] == "client-001"
        assert task["status"] == "queued"
        assert task["mode"] == "generate"
        assert task["prompt"] == "a clean product photo"
        assert task["model"] == "gpt-image-2"
        assert task["size"] == "1024x1024"
        assert task["quality"] == "auto"

    def test_required_gateway_missing_marks_task_error_without_local_fallback(self):
        identity = {"id": "user-1", "role": "user", "image_quota": 10}
        local_handler_called = False

        def local_handler(_payload):
            nonlocal local_handler_called
            local_handler_called = True
            return {"data": [{"url": "http://local.test/image.png"}]}

        service = self.make_service(generation_handler=local_handler)

        with patch("services.image_task_service.auth_service.reserve_image_quota", return_value=False), \
             patch("services.model_gateway_service.is_required", return_value=True), \
             patch("services.model_gateway_service.is_enabled", return_value=False):
            task = service.submit_generation(
                identity,
                client_task_id="missing-gateway",
                prompt="a clean product photo",
                model="gpt-image-2",
                size=None,
                quality="auto",
            )
            wait_for_task(service, identity, "missing-gateway", "error", timeout=3)

        saved = service.list_tasks(identity, ["missing-gateway"])["items"][0]
        assert task["status"] == "queued"
        assert saved["status"] == "error"
        assert "model gateway is not configured" in saved["error"]
        assert local_handler_called is False

    def test_duplicate_submit_uses_existing_task(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            calls = 0

            def handler(_payload):
                nonlocal calls
                calls += 1
                time.sleep(0.05)
                return {"data": [{"url": "http://example.test/image.png"}]}

            service = self.make_service(Path(tmp_dir) / "image_tasks.json", handler)
            first = service.submit_generation(
                OWNER,
                client_task_id="task-1",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )
            second = service.submit_generation(
                OWNER,
                client_task_id="task-1",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )

            self.assertEqual(first["id"], "task-1")
            self.assertEqual(second["id"], "task-1")
            task = wait_for_task(service, OWNER, "task-1", "success")
            self.assertEqual(task["data"][0]["url"], "http://example.test/image.png")
            self.assertEqual(calls, 1)

    def test_different_owner_cannot_query_task(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self.make_service(Path(tmp_dir) / "image_tasks.json")
            service.submit_generation(
                OWNER,
                client_task_id="private-task",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )

            wait_for_task(service, OWNER, "private-task", "success")
            result = service.list_tasks(OTHER_OWNER, ["private-task"])

            self.assertEqual(result["items"], [])
            self.assertEqual(result["missing_ids"], ["private-task"])

    def test_success_task_persists_to_new_service_instance(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "image_tasks.json"
            service = self.make_service(path)
            service.submit_generation(
                OWNER,
                client_task_id="persisted-task",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )
            wait_for_task(service, OWNER, "persisted-task", "success")

            reloaded = self.make_service(path)
            result = reloaded.list_tasks(OWNER, ["persisted-task"])

            self.assertEqual(result["missing_ids"], [])
            self.assertEqual(result["items"][0]["status"], "success")
            self.assertEqual(result["items"][0]["data"][0]["url"], "http://example.test/image.png")

    def test_image_feedback_persists_and_can_be_changed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "image_tasks.json"
            service = self.make_service(path)
            service.submit_generation(
                OWNER,
                client_task_id="feedback-task",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )
            wait_for_task(service, OWNER, "feedback-task", "success")

            liked = service.set_image_feedback(OWNER, task_id="feedback-task", image_index=0, vote="like")
            self.assertEqual(liked["data"][0]["feedback"]["vote"], "like")
            self.assertEqual(liked["data"][0]["feedback"]["likes"], 1)

            disliked = service.set_image_feedback(OWNER, task_id="feedback-task", image_index=0, vote="dislike")
            self.assertEqual(disliked["data"][0]["feedback"]["vote"], "dislike")
            self.assertEqual(disliked["data"][0]["feedback"]["dislikes"], 1)

            reloaded = self.make_service(path)
            result = reloaded.list_tasks(OWNER, ["feedback-task"])
            self.assertEqual(result["items"][0]["data"][0]["feedback"]["vote"], "dislike")

            cleared = reloaded.set_image_feedback(OWNER, task_id="feedback-task", image_index=0, vote=None)
            self.assertNotIn("feedback", cleared["data"][0])

    def test_startup_marks_unfinished_tasks_as_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "image_tasks.json"
            path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "queued-task",
                                "owner_id": "owner-1",
                                "status": "queued",
                                "mode": "generate",
                                "model": "gpt-image-2",
                                "created_at": "2099-01-01 00:00:00",
                                "updated_at": "2099-01-01 00:00:00",
                            },
                            {
                                "id": "running-task",
                                "owner_id": "owner-1",
                                "status": "running",
                                "mode": "generate",
                                "model": "gpt-image-2",
                                "created_at": "2099-01-01 00:00:00",
                                "updated_at": "2099-01-01 00:00:00",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            service = self.make_service(path)
            result = service.list_tasks(OWNER, ["queued-task", "running-task"])

            self.assertEqual([item["status"] for item in result["items"]], ["error", "error"])
            self.assertTrue(all("已中断" in item.get("error", "") for item in result["items"]))

    def test_success_task_persists_to_database_store(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_url = f"sqlite:///{Path(tmp_dir) / 'tasks.db'}"
            path = Path(tmp_dir) / "image_tasks.json"
            service = ImageTaskService(
                path,
                generation_handler=lambda _payload: {"data": [{"url": "http://example.test/image.png"}]},
                edit_handler=lambda _payload: {"data": [{"url": "http://example.test/edit.png"}]},
                retention_days_getter=lambda: 30,
                task_store=DatabaseImageTaskStore(db_url),
            )
            service.submit_generation(
                OWNER,
                client_task_id="db-task",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )
            wait_for_task(service, OWNER, "db-task", "success")

            reloaded = ImageTaskService(
                path,
                generation_handler=lambda _payload: {"data": [{"url": "unused"}]},
                edit_handler=lambda _payload: {"data": [{"url": "unused"}]},
                retention_days_getter=lambda: 30,
                task_store=DatabaseImageTaskStore(db_url),
            )
            result = reloaded.list_tasks(OWNER, ["db-task"])

            self.assertEqual(result["missing_ids"], [])
            self.assertEqual(result["items"][0]["status"], "success")
            self.assertEqual(result["items"][0]["data"][0]["url"], "http://example.test/image.png")

    def test_database_store_imports_existing_json_tasks_when_empty(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "image_tasks.json"
            path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "legacy-task",
                                "owner_id": "owner-1",
                                "status": "success",
                                "mode": "generate",
                                "model": "gpt-image-2",
                                "created_at": "2099-01-01 00:00:00",
                                "updated_at": "2099-01-01 00:00:00",
                                "data": [{"url": "http://example.test/legacy.png"}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            db_url = f"sqlite:///{Path(tmp_dir) / 'tasks.db'}"

            service = ImageTaskService(
                path,
                generation_handler=lambda _payload: {"data": [{"url": "unused"}]},
                edit_handler=lambda _payload: {"data": [{"url": "unused"}]},
                retention_days_getter=lambda: 30,
                task_store=DatabaseImageTaskStore(db_url),
            )
            result = service.list_tasks(OWNER, ["legacy-task"])

            self.assertEqual(result["missing_ids"], [])
            self.assertEqual(result["items"][0]["data"][0]["url"], "http://example.test/legacy.png")

            reloaded = ImageTaskService(
                path,
                generation_handler=lambda _payload: {"data": [{"url": "unused"}]},
                edit_handler=lambda _payload: {"data": [{"url": "unused"}]},
                retention_days_getter=lambda: 30,
                task_store=DatabaseImageTaskStore(db_url),
            )
            self.assertEqual(reloaded.list_tasks(OWNER, ["legacy-task"])["missing_ids"], [])


if __name__ == "__main__":
    unittest.main()
