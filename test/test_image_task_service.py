from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from services.image_storage_service import StoredImage
from services.image_task_store import DatabaseImageTaskStore
from services.image_task_service import ImageTaskService


GATEWAY_FIELDS = {
    "model_provider": "newapi",
    "model_base_url": "https://gateway.example.test/v1",
    "model_api_key": "sk-user-provider",
}
OWNER = {"id": "owner-1", "name": "Owner", "role": "admin", **GATEWAY_FIELDS}
OTHER_OWNER = {"id": "owner-2", "name": "Other", "role": "user", **GATEWAY_FIELDS}


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


def wait_for_mock_calls(mock_obj, count: int, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if mock_obj.call_count >= count:
            return
        time.sleep(0.02)
    raise AssertionError(f"mock did not reach {count} calls, got {mock_obj.call_count}")


class ImageTaskServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._generation_handler = lambda _payload: {"data": [{"b64_json": "cG5nLWRhdGE="}]}
        self._edit_handler = lambda _payload: {"data": [{"b64_json": "ZWRpdC1kYXRh"}]}
        self._stored_image = StoredImage(
            rel="2026/06/21/generated.png",
            url="http://api.test/images/2026/06/21/generated.png?hi_img_token=test",
            storage="local",
            size=8,
        )
        self._image_save_patcher = patch(
            "services.image_task_service.image_storage_service.save",
            side_effect=lambda *_args, **_kwargs: self._stored_image,
        )
        self._gateway_generate_patcher = patch(
            "services.model_gateway_service._request_json",
            side_effect=lambda _path, _body, payload: self._generation_handler(payload),
        )
        self._gateway_edit_patcher = patch(
            "services.model_gateway_service.edit_image",
            side_effect=lambda payload: self._edit_handler(payload),
        )
        self._gateway_generate_patcher.start()
        self._gateway_edit_patcher.start()
        self._image_save_patcher.start()

    def tearDown(self) -> None:
        self._image_save_patcher.stop()
        self._gateway_generate_patcher.stop()
        self._gateway_edit_patcher.stop()

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
        self._generation_handler = generation_handler or handler or (lambda _payload: {"data": [{"b64_json": "cG5nLWRhdGE="}]})
        self._edit_handler = edit_handler or handler or (lambda _payload: {"data": [{"b64_json": "ZWRpdC1kYXRh"}]})
        return ImageTaskService(
            path,
            generation_handler=generation_handler
            or handler
            or (lambda _payload: {"data": [{"b64_json": "cG5nLWRhdGE="}]}),
            edit_handler=edit_handler
            or handler
            or (lambda _payload: {"data": [{"b64_json": "ZWRpdC1kYXRh"}]}),
            retention_days_getter=lambda: 30,
        )

    def test_submit_generation_returns_prompt_and_client_task_metadata(self):
        identity = {"id": "user-1", "role": "admin", **GATEWAY_FIELDS}

        def handler(_payload):
            time.sleep(0.05)
            return {
                "data": [{"b64_json": "cG5nLWRhdGE="}],
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
            client_conversation_id="conversation-1",
            client_turn_id="turn-1",
            client_image_id="image-1",
        )

        assert task["id"] == "client-001"
        assert task["status"] == "queued"
        assert task["mode"] == "generate"
        assert task["prompt"] == "a clean product photo"
        assert task["model"] == "gpt-image-2"
        assert task["size"] == "1024x1024"
        assert task["quality"] == "auto"
        assert task["client_conversation_id"] == "conversation-1"
        assert task["client_turn_id"] == "turn-1"
        assert task["client_image_id"] == "image-1"

        saved = service.list_tasks(identity, ["client-001"])["items"][0]
        assert saved["client_conversation_id"] == "conversation-1"
        assert saved["client_turn_id"] == "turn-1"
        assert saved["client_image_id"] == "image-1"

    def test_linked_generation_updates_conversation_result_on_running_and_success(self):
        identity = {"id": "user-1", "role": "admin", **GATEWAY_FIELDS}

        def handler(_payload):
            return {
                "data": [{"b64_json": "cG5nLWRhdGE=", "revised_prompt": "a revised product photo"}],
                "usage": {"total_tokens": 1},
            }

        service = self.make_service(generation_handler=handler)

        with patch("services.image_conversation_service.image_conversation_service.update_result") as update_result:
            service.submit_generation(
                identity,
                client_task_id="linked-success-001",
                prompt="a clean product photo",
                model="gpt-image-2",
                size="1024x1024",
                quality="auto",
                base_url="http://api.test",
                client_conversation_id="conversation-1",
                client_turn_id="turn-1",
                client_image_id="image-1",
            )
            task = wait_for_task(service, identity, "linked-success-001", "success", timeout=3)
            wait_for_mock_calls(update_result, 2, timeout=3)

        self.assertEqual(update_result.call_count, 2)
        update_result.assert_any_call(
            identity,
            conversation_id="conversation-1",
            image_id="image-1",
            updates={"status": "loading", "taskStatus": "running"},
        )
        update_result.assert_any_call(
            identity,
            conversation_id="conversation-1",
            image_id="image-1",
            updates={
                "status": "success",
                "taskStatus": None,
                "progress": None,
                "error": None,
                "url": task["data"][0]["url"],
                "revised_prompt": "a revised product photo",
                "durationMs": task["duration_ms"],
            },
        )

    def test_linked_generation_updates_conversation_result_on_error(self):
        identity = {"id": "user-1", "role": "admin", **GATEWAY_FIELDS}

        def handler(_payload):
            raise RuntimeError("gateway quota exhausted")

        service = self.make_service(generation_handler=handler)

        with patch("services.image_conversation_service.image_conversation_service.update_result") as update_result:
            service.submit_generation(
                identity,
                client_task_id="linked-error-001",
                prompt="a clean product photo",
                model="gpt-image-2",
                size="1024x1024",
                quality="auto",
                base_url="http://api.test",
                client_conversation_id="conversation-1",
                client_turn_id="turn-1",
                client_image_id="image-1",
            )
            task = wait_for_task(service, identity, "linked-error-001", "error", timeout=3)
            wait_for_mock_calls(update_result, 2, timeout=3)

        self.assertEqual(update_result.call_count, 2)
        update_result.assert_any_call(
            identity,
            conversation_id="conversation-1",
            image_id="image-1",
            updates={"status": "loading", "taskStatus": "running"},
        )
        update_result.assert_any_call(
            identity,
            conversation_id="conversation-1",
            image_id="image-1",
            updates={
                "status": "error",
                "taskStatus": None,
                "progress": None,
                "error": "模型供应商额度不足，请先充值或更换供应商后再试。",
                "durationMs": task["duration_ms"],
            },
        )

    def test_unlinked_generation_does_not_update_conversation_result(self):
        identity = {"id": "user-1", "role": "admin", **GATEWAY_FIELDS}
        service = self.make_service()

        with patch("services.image_conversation_service.image_conversation_service.update_result") as update_result:
            service.submit_generation(
                identity,
                client_task_id="unlinked-001",
                prompt="a clean product photo",
                model="gpt-image-2",
                size="1024x1024",
                quality="auto",
                base_url="http://api.test",
            )
            wait_for_task(service, identity, "unlinked-001", "success", timeout=3)

        update_result.assert_not_called()

    def test_conversation_update_failure_does_not_fail_task(self):
        identity = {"id": "user-1", "role": "admin", **GATEWAY_FIELDS}
        service = self.make_service()

        with patch(
            "services.image_conversation_service.image_conversation_service.update_result",
            side_effect=RuntimeError("conversation store unavailable"),
        ) as update_result:
            service.submit_generation(
                identity,
                client_task_id="linked-conversation-update-fails",
                prompt="a clean product photo",
                model="gpt-image-2",
                size="1024x1024",
                quality="auto",
                base_url="http://api.test",
                client_conversation_id="conversation-1",
                client_turn_id="turn-1",
                client_image_id="image-1",
            )
            task = wait_for_task(service, identity, "linked-conversation-update-fails", "success", timeout=3)

        self.assertEqual(task["status"], "success")
        self.assertGreaterEqual(update_result.call_count, 1)

    def test_required_gateway_missing_marks_task_error_without_local_fallback(self):
        identity = {"id": "user-1", "role": "user"}
        local_handler_called = False

        def local_handler(_payload):
            nonlocal local_handler_called
            local_handler_called = True
            return {"data": [{"b64_json": "cG5nLWRhdGE="}]}

        service = self.make_service(generation_handler=local_handler)

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
        assert saved["error"] == "请先在用户设置中配置模型供应商 Base URL 和 API Key。"
        assert local_handler_called is False

    def test_duplicate_client_task_id_returns_existing_task_without_second_gateway_call(self):
        identity = {"id": "user-1", "role": "user", **GATEWAY_FIELDS}
        calls = 0

        def handler(_payload):
            nonlocal calls
            calls += 1
            return {"data": [{"b64_json": "cG5nLWRhdGE="}]}

        service = self.make_service(generation_handler=handler)

        first = service.submit_generation(
            identity,
            client_task_id="dupe-001",
            prompt="first prompt",
            model="gpt-image-2",
            size=None,
            quality="auto",
        )
        second = service.submit_generation(
            identity,
            client_task_id="dupe-001",
            prompt="second prompt",
            model="gpt-image-2",
            size=None,
            quality="auto",
        )
        wait_for_task(service, identity, "dupe-001", "success", timeout=3)

        assert first["id"] == second["id"] == "dupe-001"
        assert second["prompt"] == "first prompt"
        assert calls == 1

    def test_gateway_failure_is_persisted_as_restorable_error_task(self):
        identity = {"id": "user-1", "role": "user", **GATEWAY_FIELDS}

        def handler(_payload):
            raise RuntimeError("gateway quota exhausted")

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "image_tasks.json"
            service = self.make_service(path, generation_handler=handler)
            service.submit_generation(
                identity,
                client_task_id="gateway-error-001",
                prompt="a clean product photo",
                model="gpt-image-2",
                size=None,
                quality="auto",
            )
            wait_for_task(service, identity, "gateway-error-001", "error", timeout=3)

            reloaded = self.make_service(path)
            task = reloaded.list_tasks(identity, ["gateway-error-001"])["items"][0]
            assert task["status"] == "error"
            assert task["prompt"] == "a clean product photo"
        assert task["error"] == "模型供应商额度不足，请先充值或更换供应商后再试。"

    def test_gateway_remote_url_is_materialized_to_local_storage(self):
        identity = {"id": "user-1", "role": "user", **GATEWAY_FIELDS}
        service = self.make_service()
        stored = StoredImage(
            rel="2026/06/21/generated.png",
            url="http://api.test/images/2026/06/21/generated.png?hi_img_token=test",
            storage="local",
            size=8,
        )

        with patch("services.model_gateway_service.generate_image", return_value={"data": [{"url": "https://gateway.test/image.png"}]}), \
             patch("services.image_task_service._download_remote_image", return_value=b"png-data") as download, \
             patch("services.image_task_service.image_storage_service.save", return_value=stored) as save:
            service.submit_generation(
                identity,
                client_task_id="gateway-local-image",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://api.test",
            )
            task = wait_for_task(service, identity, "gateway-local-image", "success", timeout=3)

        download.assert_called_once_with("https://gateway.test/image.png")
        save.assert_called_once_with(b"png-data", base_url="http://api.test", owner_id="user-1")
        self.assertEqual(task["data"][0]["url"], stored.url)
        self.assertEqual(task["data"][0]["source_url"], "https://gateway.test/image.png")
        self.assertEqual(task["data"][0]["path"], stored.rel)

    def test_duplicate_submit_uses_existing_task(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            calls = 0

            def handler(_payload):
                nonlocal calls
                calls += 1
                time.sleep(0.05)
                return {"data": [{"b64_json": "cG5nLWRhdGE="}]}

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
            self.assertEqual(task["data"][0]["url"], self._stored_image.url)
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
            self.assertEqual(result["items"][0]["data"][0]["url"], self._stored_image.url)

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
                                "client_conversation_id": "conversation-1",
                                "client_image_id": "image-1",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch("services.image_conversation_service.image_conversation_service.update_result") as update_result:
                service = self.make_service(path)
            result = service.list_tasks(OWNER, ["queued-task", "running-task"])

            self.assertEqual([item["status"] for item in result["items"]], ["error", "error"])
            self.assertTrue(all("已中断" in item.get("error", "") for item in result["items"]))
            update_result.assert_called_once_with(
                {"id": "owner-1"},
                conversation_id="conversation-1",
                image_id="image-1",
                updates={
                    "status": "error",
                    "taskStatus": None,
                    "progress": None,
                    "error": "服务已重启，未完成的图片任务已中断",
                },
            )

    def test_success_task_persists_to_database_store(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_url = f"sqlite:///{Path(tmp_dir) / 'tasks.db'}"
            path = Path(tmp_dir) / "image_tasks.json"
            service = ImageTaskService(
                path,
                generation_handler=lambda _payload: {"data": [{"b64_json": "cG5nLWRhdGE="}]},
                edit_handler=lambda _payload: {"data": [{"b64_json": "ZWRpdC1kYXRh"}]},
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
            self.assertEqual(result["items"][0]["data"][0]["url"], self._stored_image.url)

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
