from __future__ import annotations

import unittest
from unittest import mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import api.image_conversations as image_conversations_api


AUTH_HEADERS = {"Authorization": "Bearer happytoken"}


class FakeImageConversationService:
    def __init__(self):
        self.items = {}

    def list_conversations(self, identity):
        return [
            item
            for item in self.items.values()
            if item["ownerId"] == identity["id"] and not item.get("deletedAt")
        ]

    def upsert_conversation(self, identity, *, conversation_id, title=""):
        item = self.items.get(conversation_id)
        if item and item["ownerId"] != identity["id"]:
            raise ValueError("conversation not found")
        item = item or {
            "id": conversation_id,
            "ownerId": identity["id"],
            "title": "",
            "createdAt": "2026-06-21 00:00:00",
            "updatedAt": "2026-06-21 00:00:00",
            "turns": [],
        }
        item["title"] = title
        self.items[conversation_id] = item
        return item

    def create_turn(self, identity, *, conversation_id, turn):
        item = self.items.get(conversation_id)
        if item is None or item["ownerId"] != identity["id"]:
            raise ValueError("conversation not found")
        item["turns"] = [turn]
        return item

    def update_turn(self, identity, *, conversation_id, turn_id, updates):
        item = self.items.get(conversation_id)
        if item is None or item["ownerId"] != identity["id"]:
            raise ValueError("conversation not found")
        for turn in item["turns"]:
            if turn["id"] == turn_id:
                turn.update(updates)
                return item
        raise ValueError("turn not found")

    def update_result(self, identity, *, conversation_id, image_id, updates):
        item = self.items.get(conversation_id)
        if item is None or item["ownerId"] != identity["id"]:
            raise ValueError("conversation not found")
        for turn in item["turns"]:
            for image in turn.get("images", []):
                if image["id"] == image_id:
                    image.update(updates)
                    return item
        raise ValueError("image not found")

    def delete_conversation(self, identity, conversation_id):
        item = self.items.get(conversation_id)
        if item is None or item["ownerId"] != identity["id"]:
            raise ValueError("conversation not found")
        item["deletedAt"] = "2026-06-21 00:01:00"
        return {"ok": True}


class ImageConversationsApiTests(unittest.TestCase):
    def setUp(self):
        self.fake_service = FakeImageConversationService()
        self.service_patcher = mock.patch.object(
            image_conversations_api, "image_conversation_service", self.fake_service
        )
        self.auth_patcher = mock.patch.object(
            image_conversations_api, "require_identity", side_effect=self.fake_identity
        )
        self.service_patcher.start()
        self.auth_patcher.start()
        self.addCleanup(self.service_patcher.stop)
        self.addCleanup(self.auth_patcher.stop)
        app = FastAPI()
        app.include_router(image_conversations_api.create_router())
        self.client = TestClient(app)

    def fake_identity(self, authorization: str | None, _request=None):
        if authorization == AUTH_HEADERS["Authorization"]:
            return {"id": "owner-1", "name": "Owner", "role": "user"}
        raise HTTPException(status_code=401, detail={"error": "unauthorized"})

    def test_upsert_list_create_turn_update_turn_update_result_and_delete(self):
        upserted = self.client.put(
            "/api/image-conversations/conv-1",
            headers=AUTH_HEADERS,
            json={"title": "Cats"},
        )
        self.assertEqual(upserted.status_code, 200, upserted.text)
        self.assertEqual(upserted.json()["item"]["title"], "Cats")

        listed = self.client.get("/api/image-conversations", headers=AUTH_HEADERS)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([item["id"] for item in listed.json()["items"]], ["conv-1"])

        turn_body = {
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
        }
        turn_response = self.client.post(
            "/api/image-conversations/conv-1/turns",
            headers=AUTH_HEADERS,
            json=turn_body,
        )
        self.assertEqual(turn_response.status_code, 200, turn_response.text)
        self.assertEqual(turn_response.json()["item"]["turns"][0]["id"], "turn-1")

        turn_patch_response = self.client.patch(
            "/api/image-conversations/conv-1/turns/turn-1",
            headers=AUTH_HEADERS,
            json={"status": "generating", "promptDeleted": True},
        )
        self.assertEqual(turn_patch_response.status_code, 200, turn_patch_response.text)
        patched_turn = turn_patch_response.json()["item"]["turns"][0]
        self.assertEqual(patched_turn["status"], "generating")
        self.assertTrue(patched_turn["promptDeleted"])

        result_response = self.client.patch(
            "/api/image-conversations/conv-1/results/image-1",
            headers=AUTH_HEADERS,
            json={"status": "success", "url": "http://api.test/images/cat.png"},
        )
        self.assertEqual(result_response.status_code, 200, result_response.text)
        self.assertEqual(result_response.json()["item"]["turns"][0]["images"][0]["status"], "success")

        delete_response = self.client.delete("/api/image-conversations/conv-1", headers=AUTH_HEADERS)
        self.assertEqual(delete_response.status_code, 200, delete_response.text)
        self.assertEqual(delete_response.json(), {"ok": True})

    def test_mutation_failures_return_404(self):
        response = self.client.patch(
            "/api/image-conversations/missing/turns/turn-1",
            headers=AUTH_HEADERS,
            json={"status": "error"},
        )
        self.assertEqual(response.status_code, 404)

    def test_requires_login(self):
        response = self.client.get("/api/image-conversations")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
