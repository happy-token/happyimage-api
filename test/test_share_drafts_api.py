from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import api.share_drafts as share_drafts_api
import services.gallery_prompt_service as gallery_prompt_service
from services.share_draft_service import ShareDraftService


AUTH_HEADERS = {"Authorization": "Bearer happytoken"}


def make_draft_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "source": "user_gallery",
        "image_url": "/images/cat.png",
        "conversation_id": "conv-1",
        "turn_id": "turn-1",
        "image_id": "image-1",
        "original_prompt": "a cat wearing a tiny hat",
        "conversation_summary": "cat design",
        "share_prompt": "make a cat poster",
        "title": "Cat poster",
        "category": "poster",
        "tags": ["cat", "poster"],
        "status": "draft",
    }
    payload.update(overrides)
    return payload


class ShareDraftsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        service = ShareDraftService(Path(self.tmp_dir.name) / "share_drafts.json")

        def fake_require_identity(authorization: str | None):
            if authorization == AUTH_HEADERS["Authorization"]:
                return {"id": "admin", "name": "管理员", "role": "admin"}
            raise HTTPException(status_code=401, detail={"error": "unauthorized"})

        self.service_patcher = mock.patch.object(share_drafts_api, "share_draft_service", service)
        self.auth_patcher = mock.patch.object(share_drafts_api, "require_identity", side_effect=fake_require_identity)
        self.summary_patcher = mock.patch.object(
            share_drafts_api,
            "generate_conversation_summary",
            return_value="mock conversation summary",
        )
        self.prompt_patcher = mock.patch.object(
            share_drafts_api,
            "generate_share_prompt",
            return_value="mock share prompt",
        )
        self.service_patcher.start()
        self.auth_patcher.start()
        self.summary_patcher.start()
        self.prompt_patcher.start()
        self.addCleanup(self.service_patcher.stop)
        self.addCleanup(self.auth_patcher.stop)
        self.addCleanup(self.summary_patcher.stop)
        self.addCleanup(self.prompt_patcher.stop)

        app = FastAPI()
        app.include_router(share_drafts_api.create_router())
        self.client = TestClient(app)

    def test_save_then_list_share_drafts(self) -> None:
        save_response = self.client.post("/api/share-drafts", headers=AUTH_HEADERS, json=make_draft_payload())
        self.assertEqual(save_response.status_code, 200, save_response.text)
        saved_item = save_response.json()["item"]
        self.assertEqual(saved_item["image_id"], "image-1")
        self.assertEqual(saved_item["title"], "Cat poster")
        self.assertEqual(saved_item["owner_id"], "admin")

        list_response = self.client.get("/api/share-drafts", headers=AUTH_HEADERS)
        self.assertEqual(list_response.status_code, 200, list_response.text)
        items = list_response.json()["items"]

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["image_id"], "image-1")
        self.assertEqual(items[0]["title"], "Cat poster")
        self.assertEqual(items[0]["owner_id"], "admin")

    def test_summarize_returns_mock_summary(self) -> None:
        response = self.client.post(
            "/api/user-gallery/summarize",
            headers=AUTH_HEADERS,
            json={
                "conversation_id": "conv-1",
                "conversation_title": "Cat ideas",
                "original_prompt": "a cat wearing a tiny hat",
                "image_url": "/images/cat.png",
                "conversation_messages": [{"role": "user", "content": "make a cat"}],
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"summary": "mock conversation summary"})

    def test_generate_share_prompt_returns_mock_share_prompt(self) -> None:
        response = self.client.post(
            "/api/user-gallery/generate-share-prompt",
            headers=AUTH_HEADERS,
            json={
                "conversation_id": "conv-1",
                "conversation_title": "Cat ideas",
                "original_prompt": "a cat wearing a tiny hat",
                "image_url": "/images/cat.png",
                "conversation_summary": "cat design",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"share_prompt": "mock share prompt"})

    def test_summarize_rejects_overlong_original_prompt(self) -> None:
        response = self.client.post(
            "/api/user-gallery/summarize",
            headers=AUTH_HEADERS,
            json={
                "conversation_id": "conv-1",
                "original_prompt": "x" * 8001,
                "image_url": "/images/cat.png",
            },
        )

        self.assertEqual(response.status_code, 422, response.text)

    def test_summarize_rejects_overlong_conversation_id(self) -> None:
        response = self.client.post(
            "/api/user-gallery/summarize",
            headers=AUTH_HEADERS,
            json={
                "conversation_id": "x" * 101,
                "original_prompt": "a cat wearing a tiny hat",
                "image_url": "/images/cat.png",
            },
        )

        self.assertEqual(response.status_code, 422, response.text)

    def test_summarize_rejects_too_many_conversation_messages(self) -> None:
        response = self.client.post(
            "/api/user-gallery/summarize",
            headers=AUTH_HEADERS,
            json={
                "conversation_id": "conv-1",
                "original_prompt": "a cat wearing a tiny hat",
                "image_url": "/images/cat.png",
                "conversation_messages": [{"role": "user", "content": "hello"} for _ in range(41)],
            },
        )

        self.assertEqual(response.status_code, 422, response.text)

    def test_summarize_rejects_overlong_conversation_message_role(self) -> None:
        response = self.client.post(
            "/api/user-gallery/summarize",
            headers=AUTH_HEADERS,
            json={
                "conversation_id": "conv-1",
                "original_prompt": "a cat wearing a tiny hat",
                "image_url": "/images/cat.png",
                "conversation_messages": [{"role": "x" * 33, "content": "hello"}],
            },
        )

        self.assertEqual(response.status_code, 422, response.text)

    def test_summarize_rejects_overlong_conversation_message_content(self) -> None:
        response = self.client.post(
            "/api/user-gallery/summarize",
            headers=AUTH_HEADERS,
            json={
                "conversation_id": "conv-1",
                "original_prompt": "a cat wearing a tiny hat",
                "image_url": "/images/cat.png",
                "conversation_messages": [{"role": "user", "content": "x" * 4001}],
            },
        )

        self.assertEqual(response.status_code, 422, response.text)

    def test_save_missing_required_field_returns_400(self) -> None:
        response = self.client.post(
            "/api/share-drafts",
            headers=AUTH_HEADERS,
            json=make_draft_payload(image_url=" "),
        )

        self.assertEqual(response.status_code, 400, response.text)

    def test_save_rejects_overlong_original_prompt(self) -> None:
        response = self.client.post(
            "/api/share-drafts",
            headers=AUTH_HEADERS,
            json=make_draft_payload(original_prompt="x" * 8001),
        )

        self.assertEqual(response.status_code, 422, response.text)

    def test_save_rejects_overlong_share_prompt(self) -> None:
        response = self.client.post(
            "/api/share-drafts",
            headers=AUTH_HEADERS,
            json=make_draft_payload(share_prompt="x" * 8001),
        )

        self.assertEqual(response.status_code, 422, response.text)

    def test_save_rejects_overlong_title(self) -> None:
        response = self.client.post(
            "/api/share-drafts",
            headers=AUTH_HEADERS,
            json=make_draft_payload(title="x" * 201),
        )

        self.assertEqual(response.status_code, 422, response.text)

    def test_save_rejects_too_many_tags(self) -> None:
        response = self.client.post(
            "/api/share-drafts",
            headers=AUTH_HEADERS,
            json=make_draft_payload(tags=[f"tag-{index}" for index in range(21)]),
        )

        self.assertEqual(response.status_code, 422, response.text)

    def test_save_rejects_overlong_tag(self) -> None:
        response = self.client.post(
            "/api/share-drafts",
            headers=AUTH_HEADERS,
            json=make_draft_payload(tags=["x" * 51]),
        )

        self.assertEqual(response.status_code, 422, response.text)

    def test_missing_auth_returns_401(self) -> None:
        response = self.client.get("/api/share-drafts")

        self.assertEqual(response.status_code, 401, response.text)


class GalleryPromptServiceTests(unittest.TestCase):
    def test_summary_falls_back_to_original_prompt(self) -> None:
        summary = gallery_prompt_service.generate_conversation_summary({
            "original_prompt": "a cat wearing a tiny hat",
            "conversation_id": "conv-1",
            "image_url": "/images/cat.png",
        })

        self.assertEqual(summary, "a cat wearing a tiny hat")


if __name__ == "__main__":
    unittest.main()
