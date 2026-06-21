# Image Conversation Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist image workspace conversations, turns, and results on the server so a fresh browser loads one correct conversation instead of reconstructing sessions from image tasks.

**Architecture:** Add a server-side image conversation service/store as the authoritative history model. Keep `image_tasks` as the async execution layer, linked to conversation results by client IDs, and move the frontend `/image` page to load and mutate server conversations while retaining local storage only as cache.

**Tech Stack:** FastAPI, Pydantic, Python service/store classes, JSON/SQLAlchemy-backed storage, Next.js/React, TypeScript, localforage, Vitest, unittest.

---

## File Structure

Backend files:

- Create `happyimage-api/services/image_conversation_store.py`: JSON and database persistence for nested conversation records.
- Create `happyimage-api/services/image_conversation_service.py`: owner-scoped conversation, turn, and result operations.
- Create `happyimage-api/api/image_conversations.py`: FastAPI router for conversation CRUD and result updates.
- Modify `happyimage-api/api/app.py`: include the new router.
- Modify `happyimage-api/api/image_tasks.py`: accept `client_image_id` in generation/edit requests.
- Modify `happyimage-api/api/image_inputs.py`: parse `client_image_id` for edit forms.
- Modify `happyimage-api/services/image_task_service.py`: persist client IDs and update linked conversation results during task lifecycle.
- Test `happyimage-api/test/test_image_conversation_service.py`: service/store behavior.
- Test `happyimage-api/test/test_image_conversations_api.py`: API owner isolation and mutations.
- Modify `happyimage-api/test/test_image_task_service.py`: task/result integration.
- Modify `happyimage-api/test/test_image_tasks_api.py`: task API forwards client IDs.

Frontend files:

- Modify `happyimage-web/src/lib/api.ts`: add conversation API types/helpers and `client_image_id` task metadata.
- Modify `happyimage-web/src/store/image-conversations.ts`: keep local storage as cache only; expose cache helpers with the existing types.
- Modify `happyimage-web/src/app/image/page.tsx`: load server conversations, persist create/rename/delete/update operations, remove task-ID conversation reconstruction.
- Test `happyimage-web/src/app/image/components/user-gallery-adapter.ts` only if type changes break gallery behavior; otherwise existing tests cover gallery/prompt utilities.

---

### Task 1: Backend Conversation Store and Service

**Files:**
- Create: `/Users/forever/workspace/HappyImage/happyimage-api/services/image_conversation_store.py`
- Create: `/Users/forever/workspace/HappyImage/happyimage-api/services/image_conversation_service.py`
- Test: `/Users/forever/workspace/HappyImage/happyimage-api/test/test_image_conversation_service.py`

- [ ] **Step 1: Write failing service tests**

Create `/Users/forever/workspace/HappyImage/happyimage-api/test/test_image_conversation_service.py` with:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.image_conversation_service import ImageConversationService


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
        with self.assertRaises(ValueError):
            service.upsert_conversation(OTHER_OWNER, conversation_id="conv-1", title="Hijack")

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

    def test_soft_delete_conversation(self):
        service = self.make_service()
        service.upsert_conversation(OWNER, conversation_id="conv-1", title="Private")
        service.delete_conversation(OWNER, "conv-1")

        self.assertEqual(service.list_conversations(OWNER), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/forever/workspace/HappyImage/happyimage-api
uv run python -m unittest test.test_image_conversation_service
```

Expected: FAIL with `ModuleNotFoundError: No module named 'services.image_conversation_service'`.

- [ ] **Step 3: Implement store**

Create `/Users/forever/workspace/HappyImage/happyimage-api/services/image_conversation_store.py`:

```python
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import Column, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from services.config import DATA_DIR
from services.storage.factory import _mask_password


class ImageConversationStore(Protocol):
    def load_conversations(self) -> list[dict[str, Any]]:
        ...

    def save_conversations(self, conversations: list[dict[str, Any]]) -> None:
        ...


class JSONImageConversationStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_conversations(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        items = raw.get("conversations") if isinstance(raw, dict) else raw
        return items if isinstance(items, list) else []

    def save_conversations(self, conversations: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps({"conversations": conversations}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self.path)


ImageConversationBase = declarative_base()


class ImageConversationModel(ImageConversationBase):
    __tablename__ = "image_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_key = Column(String(512), unique=True, nullable=False, index=True)
    owner_id = Column(String(255), nullable=False, index=True)
    conversation_id = Column(String(255), nullable=False, index=True)
    updated_at = Column(String(64), nullable=False, index=True)
    data = Column(Text, nullable=False)


class DatabaseImageConversationStore:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_engine(database_url, pool_pre_ping=True, pool_recycle=3600)
        ImageConversationBase.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def load_conversations(self) -> list[dict[str, Any]]:
        session = self.Session()
        try:
            rows = session.query(ImageConversationModel).order_by(ImageConversationModel.updated_at.desc()).all()
            items: list[dict[str, Any]] = []
            for row in rows:
                try:
                    value = json.loads(row.data)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    items.append(value)
            return items
        finally:
            session.close()

    def save_conversations(self, conversations: list[dict[str, Any]]) -> None:
        session = self.Session()
        try:
            session.query(ImageConversationModel).delete()
            for item in conversations:
                owner = str(item.get("ownerId") or item.get("owner_id") or "").strip()
                conversation_id = str(item.get("id") or "").strip()
                if not owner or not conversation_id:
                    continue
                session.add(
                    ImageConversationModel(
                        conversation_key=f"{owner}:{conversation_id}",
                        owner_id=owner,
                        conversation_id=conversation_id,
                        updated_at=str(item.get("updatedAt") or item.get("updated_at") or ""),
                        data=json.dumps(item, ensure_ascii=False),
                    )
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def create_image_conversation_store(path: Path) -> ImageConversationStore:
    backend_type = os.getenv("STORAGE_BACKEND", "json").lower().strip()
    if backend_type in ("sqlite", "postgres", "postgresql", "mysql", "database"):
        database_url = os.getenv("DATABASE_URL", "").strip() or f"sqlite:///{DATA_DIR / 'accounts.db'}"
        print(f"[image-conversations] Using database storage: {_mask_password(database_url)}")
        return DatabaseImageConversationStore(database_url)
    print(f"[image-conversations] Using JSON storage: {path}")
    return JSONImageConversationStore(path)
```

- [ ] **Step 4: Implement service**

Create `/Users/forever/workspace/HappyImage/happyimage-api/services/image_conversation_service.py`:

```python
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from services.image_conversation_store import ImageConversationStore, create_image_conversation_store


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean(value: object, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return text or default


def _owner_id(identity: dict[str, object]) -> str:
    return _clean(identity.get("id")) or "anonymous"


def _task_key(owner_id: str, conversation_id: str) -> str:
    return f"{owner_id}:{conversation_id}"


def _normalize_image(value: dict[str, Any]) -> dict[str, Any]:
    item = {
        "id": _clean(value.get("id")),
        "taskId": _clean(value.get("taskId") or value.get("task_id")),
        "status": _clean(value.get("status"), "loading"),
    }
    for source, target in (
        ("taskStatus", "taskStatus"),
        ("progress", "progress"),
        ("url", "url"),
        ("revised_prompt", "revised_prompt"),
        ("error", "error"),
        ("durationMs", "durationMs"),
        ("feedback", "feedback"),
    ):
        if value.get(source) is not None:
            item[target] = value.get(source)
    return item


def _derive_turn_status(turn: dict[str, Any]) -> tuple[str, str]:
    images = [image for image in turn.get("images", []) if isinstance(image, dict)]
    if any(image.get("status") == "loading" for image in images):
        if any(image.get("taskStatus") == "running" for image in images):
            return "generating", ""
        return "queued", ""
    failures = [image for image in images if image.get("status") == "error"]
    if failures:
        return "error", f"其中 {len(failures)} 张未成功生成"
    return "success", ""


class ImageConversationService:
    def __init__(self, path: Path, *, store: ImageConversationStore | None = None):
        self.path = path
        self.store = store or create_image_conversation_store(path)
        self._lock = threading.RLock()
        self._items: dict[str, dict[str, Any]] = {}
        with self._lock:
            self._items = self._load_locked()

    def list_conversations(self, identity: dict[str, object]) -> list[dict[str, Any]]:
        owner = _owner_id(identity)
        with self._lock:
            items = [
                self._public_conversation(item)
                for item in self._items.values()
                if item.get("ownerId") == owner and not item.get("deletedAt")
            ]
        return sorted(items, key=lambda item: str(item.get("updatedAt") or ""), reverse=True)

    def upsert_conversation(self, identity: dict[str, object], *, conversation_id: str, title: str = "") -> dict[str, Any]:
        owner = _owner_id(identity)
        normalized_id = _clean(conversation_id)
        if not normalized_id:
            raise ValueError("conversation_id is required")
        key = _task_key(owner, normalized_id)
        now = _now_iso()
        with self._lock:
            existing_any_owner = next((item for item in self._items.values() if item.get("id") == normalized_id), None)
            if existing_any_owner is not None and existing_any_owner.get("ownerId") != owner:
                raise ValueError("conversation not found")
            item = self._items.get(key)
            if item is None:
                item = {
                    "id": normalized_id,
                    "ownerId": owner,
                    "title": _clean(title),
                    "createdAt": now,
                    "updatedAt": now,
                    "turns": [],
                }
            else:
                item = {**item, "title": _clean(title, item.get("title")), "updatedAt": now}
            item.pop("deletedAt", None)
            self._items[key] = item
            self._save_locked()
            return self._public_conversation(item)

    def create_turn(self, identity: dict[str, object], *, conversation_id: str, turn: dict[str, Any]) -> dict[str, Any]:
        owner = _owner_id(identity)
        key = _task_key(owner, _clean(conversation_id))
        now = _now_iso()
        with self._lock:
            conversation = self._items.get(key)
            if conversation is None or conversation.get("deletedAt"):
                raise ValueError("conversation not found")
            turn_id = _clean(turn.get("id"))
            if not turn_id:
                raise ValueError("turn.id is required")
            images = [
                _normalize_image(image)
                for image in (turn.get("images") or [])
                if isinstance(image, dict) and _clean(image.get("id"))
            ]
            next_turn = {
                "id": turn_id,
                "prompt": _clean(turn.get("prompt")),
                "model": _clean(turn.get("model"), "gpt-image-2"),
                "mode": "edit" if turn.get("mode") == "edit" else "generate",
                "referenceImages": turn.get("referenceImages") if isinstance(turn.get("referenceImages"), list) else [],
                "count": max(1, int(turn.get("count") or len(images) or 1)),
                "size": _clean(turn.get("size")),
                "ratio": _clean(turn.get("ratio"), "1:1"),
                "tier": _clean(turn.get("tier"), "1k"),
                "quality": _clean(turn.get("quality"), "auto"),
                "images": images,
                "createdAt": _clean(turn.get("createdAt"), now),
                "status": _clean(turn.get("status"), "queued"),
            }
            turns = [candidate for candidate in conversation.get("turns", []) if candidate.get("id") != turn_id]
            turns.append(next_turn)
            conversation["turns"] = turns
            conversation["updatedAt"] = now
            self._items[key] = conversation
            self._save_locked()
            return self._public_conversation(conversation)

    def update_turn(self, identity: dict[str, object], *, conversation_id: str, turn_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        owner = _owner_id(identity)
        key = _task_key(owner, _clean(conversation_id))
        now = _now_iso()
        with self._lock:
            conversation = self._items.get(key)
            if conversation is None:
                raise ValueError("conversation not found")
            found = False
            turns = []
            for turn in conversation.get("turns", []):
                if turn.get("id") != turn_id:
                    turns.append(turn)
                    continue
                found = True
                next_turn = dict(turn)
                for field in ("prompt", "status", "error", "promptDeleted", "resultsDeleted"):
                    if field in updates:
                        next_turn[field] = updates[field]
                turns.append(next_turn)
            if not found:
                raise ValueError("turn not found")
            conversation["turns"] = turns
            conversation["updatedAt"] = now
            self._save_locked()
            return self._public_conversation(conversation)

    def update_result(self, identity: dict[str, object], *, conversation_id: str, image_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        owner = _owner_id(identity)
        key = _task_key(owner, _clean(conversation_id))
        now = _now_iso()
        with self._lock:
            conversation = self._items.get(key)
            if conversation is None:
                raise ValueError("conversation not found")
            found = False
            next_turns = []
            for turn in conversation.get("turns", []):
                next_images = []
                turn_changed = False
                for image in turn.get("images", []):
                    if image.get("id") != image_id:
                        next_images.append(image)
                        continue
                    found = True
                    turn_changed = True
                    next_image = dict(image)
                    for field in ("taskId", "status", "taskStatus", "progress", "url", "revised_prompt", "error", "durationMs", "feedback"):
                        if field in updates:
                            next_image[field] = updates[field]
                    next_images.append(next_image)
                if turn_changed:
                    next_turn = {**turn, "images": next_images}
                    status, error = _derive_turn_status(next_turn)
                    next_turn["status"] = status
                    if error:
                        next_turn["error"] = error
                    else:
                        next_turn.pop("error", None)
                    next_turns.append(next_turn)
                else:
                    next_turns.append(turn)
            if not found:
                raise ValueError("image not found")
            conversation["turns"] = next_turns
            conversation["updatedAt"] = now
            self._save_locked()
            return self._public_conversation(conversation)

    def delete_conversation(self, identity: dict[str, object], conversation_id: str) -> dict[str, Any]:
        owner = _owner_id(identity)
        key = _task_key(owner, _clean(conversation_id))
        now = _now_iso()
        with self._lock:
            conversation = self._items.get(key)
            if conversation is None:
                raise ValueError("conversation not found")
            conversation["deletedAt"] = now
            conversation["updatedAt"] = now
            self._save_locked()
            return {"ok": True}

    def _load_locked(self) -> dict[str, dict[str, Any]]:
        items: dict[str, dict[str, Any]] = {}
        for raw in self.store.load_conversations():
            if not isinstance(raw, dict):
                continue
            owner = _clean(raw.get("ownerId") or raw.get("owner_id"))
            conversation_id = _clean(raw.get("id"))
            if not owner or not conversation_id:
                continue
            item = {
                "id": conversation_id,
                "ownerId": owner,
                "title": _clean(raw.get("title")),
                "createdAt": _clean(raw.get("createdAt") or raw.get("created_at"), _now_iso()),
                "updatedAt": _clean(raw.get("updatedAt") or raw.get("updated_at"), _now_iso()),
                "turns": raw.get("turns") if isinstance(raw.get("turns"), list) else [],
            }
            if raw.get("deletedAt") or raw.get("deleted_at"):
                item["deletedAt"] = _clean(raw.get("deletedAt") or raw.get("deleted_at"))
            items[_task_key(owner, conversation_id)] = item
        return items

    def _public_conversation(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id"),
            "ownerId": item.get("ownerId"),
            "title": item.get("title") or "",
            "createdAt": item.get("createdAt"),
            "updatedAt": item.get("updatedAt"),
            "turns": item.get("turns") if isinstance(item.get("turns"), list) else [],
        }

    def _save_locked(self) -> None:
        items = sorted(self._items.values(), key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
        self.store.save_conversations(items)


image_conversation_service = ImageConversationService(DATA_DIR / "image_conversations.json")
```

- [ ] **Step 5: Run service tests**

Run:

```bash
cd /Users/forever/workspace/HappyImage/happyimage-api
uv run python -m unittest test.test_image_conversation_service
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/forever/workspace/HappyImage/happyimage-api
git add services/image_conversation_store.py services/image_conversation_service.py test/test_image_conversation_service.py
git commit -m "feat: add image conversation service"
```

---

### Task 2: Backend Conversation API

**Files:**
- Create: `/Users/forever/workspace/HappyImage/happyimage-api/api/image_conversations.py`
- Modify: `/Users/forever/workspace/HappyImage/happyimage-api/api/app.py`
- Test: `/Users/forever/workspace/HappyImage/happyimage-api/test/test_image_conversations_api.py`

- [ ] **Step 1: Write failing API tests**

Create `/Users/forever/workspace/HappyImage/happyimage-api/test/test_image_conversations_api.py`:

```python
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
        return [item for item in self.items.values() if item["ownerId"] == identity["id"] and not item.get("deletedAt")]

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
        item = self.upsert_conversation(identity, conversation_id=conversation_id, title="Created")
        item["turns"] = [turn]
        return item

    def update_turn(self, identity, *, conversation_id, turn_id, updates):
        item = self.items[conversation_id]
        item["turns"][0].update(updates)
        return item

    def update_result(self, identity, *, conversation_id, image_id, updates):
        item = self.items[conversation_id]
        item["turns"][0]["images"][0].update(updates)
        return item

    def delete_conversation(self, identity, conversation_id):
        self.items[conversation_id]["deletedAt"] = "2026-06-21 00:01:00"
        return {"ok": True}


class ImageConversationsApiTests(unittest.TestCase):
    def setUp(self):
        self.fake_service = FakeImageConversationService()
        self.service_patcher = mock.patch.object(image_conversations_api, "image_conversation_service", self.fake_service)
        self.auth_patcher = mock.patch.object(image_conversations_api, "require_identity", side_effect=self.fake_identity)
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

    def test_upsert_list_create_turn_update_result_and_delete(self):
        upserted = self.client.put("/api/image-conversations/conv-1", headers=AUTH_HEADERS, json={"title": "Cats"})
        self.assertEqual(upserted.status_code, 200, upserted.text)
        self.assertEqual(upserted.json()["item"]["title"], "Cats")

        listed = self.client.get("/api/image-conversations", headers=AUTH_HEADERS)
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
        turn_response = self.client.post("/api/image-conversations/conv-1/turns", headers=AUTH_HEADERS, json=turn_body)
        self.assertEqual(turn_response.status_code, 200, turn_response.text)
        self.assertEqual(turn_response.json()["item"]["turns"][0]["id"], "turn-1")

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

    def test_requires_login(self):
        response = self.client.get("/api/image-conversations")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/forever/workspace/HappyImage/happyimage-api
uv run python -m unittest test.test_image_conversations_api
```

Expected: FAIL with `ModuleNotFoundError` for `api.image_conversations`.

- [ ] **Step 3: Implement router**

Create `/Users/forever/workspace/HappyImage/happyimage-api/api/image_conversations.py`:

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from api.support import require_identity
from services.image_conversation_service import image_conversation_service


class ConversationUpsertRequest(BaseModel):
    title: str = ""


class TurnCreateRequest(BaseModel):
    id: str = Field(..., min_length=1)
    prompt: str = ""
    model: str = "gpt-image-2"
    mode: str = "generate"
    referenceImages: list[dict[str, Any]] = []
    count: int = Field(default=1, ge=1)
    size: str = ""
    ratio: str = "1:1"
    tier: str = "1k"
    quality: str = "auto"
    images: list[dict[str, Any]] = []
    createdAt: str = ""
    status: str = "queued"


class TurnPatchRequest(BaseModel):
    prompt: str | None = None
    status: str | None = None
    error: str | None = None
    promptDeleted: bool | None = None
    resultsDeleted: bool | None = None


class ResultPatchRequest(BaseModel):
    taskId: str | None = None
    status: str | None = None
    taskStatus: str | None = None
    progress: str | None = None
    url: str | None = None
    revised_prompt: str | None = None
    error: str | None = None
    durationMs: int | None = None
    feedback: dict[str, Any] | None = None


def _patch_dict(model: BaseModel) -> dict[str, Any]:
    return {key: value for key, value in model.model_dump().items() if value is not None}


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/image-conversations")
    async def list_image_conversations(request: Request, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization, request)
        items = await run_in_threadpool(image_conversation_service.list_conversations, identity)
        return {"items": items}

    @router.put("/api/image-conversations/{conversation_id}")
    async def upsert_image_conversation(
        conversation_id: str,
        body: ConversationUpsertRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization, request)
        try:
            item = await run_in_threadpool(
                image_conversation_service.upsert_conversation,
                identity,
                conversation_id=conversation_id,
                title=body.title,
            )
            return {"item": item}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc

    @router.post("/api/image-conversations/{conversation_id}/turns")
    async def create_image_conversation_turn(
        conversation_id: str,
        body: TurnCreateRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization, request)
        try:
            item = await run_in_threadpool(
                image_conversation_service.create_turn,
                identity,
                conversation_id=conversation_id,
                turn=body.model_dump(),
            )
            return {"item": item}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc

    @router.patch("/api/image-conversations/{conversation_id}/turns/{turn_id}")
    async def update_image_conversation_turn(
        conversation_id: str,
        turn_id: str,
        body: TurnPatchRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization, request)
        try:
            item = await run_in_threadpool(
                image_conversation_service.update_turn,
                identity,
                conversation_id=conversation_id,
                turn_id=turn_id,
                updates=_patch_dict(body),
            )
            return {"item": item}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc

    @router.patch("/api/image-conversations/{conversation_id}/results/{image_id}")
    async def update_image_conversation_result(
        conversation_id: str,
        image_id: str,
        body: ResultPatchRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization, request)
        try:
            item = await run_in_threadpool(
                image_conversation_service.update_result,
                identity,
                conversation_id=conversation_id,
                image_id=image_id,
                updates=_patch_dict(body),
            )
            return {"item": item}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc

    @router.delete("/api/image-conversations/{conversation_id}")
    async def delete_image_conversation(
        conversation_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization, request)
        try:
            return await run_in_threadpool(image_conversation_service.delete_conversation, identity, conversation_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc

    return router
```

- [ ] **Step 4: Register router**

Modify `/Users/forever/workspace/HappyImage/happyimage-api/api/app.py` by importing and including the router. Add near other API router imports:

```python
from api import image_conversations
```

Add near other `app.include_router(...)` calls:

```python
app.include_router(image_conversations.create_router())
```

- [ ] **Step 5: Run API tests**

```bash
cd /Users/forever/workspace/HappyImage/happyimage-api
uv run python -m unittest test.test_image_conversations_api
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/forever/workspace/HappyImage/happyimage-api
git add api/image_conversations.py api/app.py test/test_image_conversations_api.py
git commit -m "feat: add image conversation api"
```

---

### Task 3: Link Image Tasks to Conversation Results

**Files:**
- Modify: `/Users/forever/workspace/HappyImage/happyimage-api/api/image_tasks.py`
- Modify: `/Users/forever/workspace/HappyImage/happyimage-api/api/image_inputs.py`
- Modify: `/Users/forever/workspace/HappyImage/happyimage-api/services/image_task_service.py`
- Modify tests: `/Users/forever/workspace/HappyImage/happyimage-api/test/test_image_tasks_api.py`
- Modify tests: `/Users/forever/workspace/HappyImage/happyimage-api/test/test_image_task_service.py`

- [ ] **Step 1: Extend failing API test for `client_image_id`**

In `/Users/forever/workspace/HappyImage/happyimage-api/test/test_image_tasks_api.py`, update `test_create_generation_task` JSON body to include:

```python
"client_image_id": "image-1",
```

Add assertion after the existing `client_turn_id` assertion:

```python
self.assertEqual(self.fake_service.generation_calls[0][1]["client_image_id"], "image-1")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/forever/workspace/HappyImage/happyimage-api
uv run python -m unittest test.test_image_tasks_api.ImageTasksApiTests.test_create_generation_task
```

Expected: FAIL with `KeyError: 'client_image_id'`.

- [ ] **Step 3: Add API request field and forwarding**

In `/Users/forever/workspace/HappyImage/happyimage-api/api/image_tasks.py`, add to `ImageGenerationTaskRequest`:

```python
client_image_id: str | None = None
```

In the `submit_generation` call, add:

```python
client_image_id=body.client_image_id or "",
```

In the `submit_edit` call, add:

```python
client_image_id=str(payload.get("client_image_id") or ""),
```

In `/Users/forever/workspace/HappyImage/happyimage-api/api/image_inputs.py`, extend `_payload_from_fields`:

```python
if "client_image_id" in fields:
    payload["client_image_id"] = _clean(fields.get("client_image_id"))
```

- [ ] **Step 4: Persist client image ID**

In `/Users/forever/workspace/HappyImage/happyimage-api/services/image_task_service.py`, update `submit_generation` and `submit_edit` signatures:

```python
client_image_id: str = "",
```

Add to both payloads:

```python
"client_image_id": client_image_id,
```

In `_submit`, persist it with the existing client ID block:

```python
client_image_id = _clean(payload.get("client_image_id"))
if client_image_id:
    task["client_image_id"] = client_image_id
```

In `_load_locked`, preserve it:

```python
client_image_id = _clean(item.get("client_image_id"))
if client_image_id:
    task["client_image_id"] = client_image_id
```

In `_public_task`, expose it:

```python
if task.get("client_image_id"):
    item["client_image_id"] = task.get("client_image_id")
```

- [ ] **Step 5: Update conversation result during task lifecycle**

In `/Users/forever/workspace/HappyImage/happyimage-api/services/image_task_service.py`, add helper methods inside `ImageTaskService`:

```python
    def _conversation_link(self, task: dict[str, Any]) -> tuple[str, str]:
        return _clean(task.get("client_conversation_id")), _clean(task.get("client_image_id"))

    def _update_linked_result(self, identity: dict[str, object], task: dict[str, Any], updates: dict[str, Any]) -> None:
        conversation_id, image_id = self._conversation_link(task)
        if not conversation_id or not image_id:
            return
        try:
            from services.image_conversation_service import image_conversation_service

            image_conversation_service.update_result(
                identity,
                conversation_id=conversation_id,
                image_id=image_id,
                updates=updates,
            )
        except Exception:
            pass
```

In `_run_task`, after `_update_task(key, status=TASK_STATUS_RUNNING, error="")`, fetch the task and update the linked result:

```python
        with self._lock:
            current_task = dict(self._tasks.get(key) or {})
        self._update_linked_result(identity, current_task, {"status": "loading", "taskStatus": "running"})
```

After success `_update_task(...)`, fetch the updated task and update the result:

```python
            with self._lock:
                current_task = dict(self._tasks.get(key) or {})
            first = data[0] if data and isinstance(data[0], dict) else {}
            self._update_linked_result(
                identity,
                current_task,
                {
                    "status": "success",
                    "taskStatus": None,
                    "progress": None,
                    "url": first.get("url"),
                    "revised_prompt": first.get("revised_prompt"),
                    "durationMs": duration_ms,
                    "error": None,
                },
            )
```

After error `_update_task(...)`, fetch the updated task and update the result:

```python
            with self._lock:
                current_task = dict(self._tasks.get(key) or {})
            self._update_linked_result(
                identity,
                current_task,
                {
                    "status": "error",
                    "taskStatus": None,
                    "progress": None,
                    "error": error_message,
                    "durationMs": duration_ms,
                },
            )
```

- [ ] **Step 6: Run backend task tests**

```bash
cd /Users/forever/workspace/HappyImage/happyimage-api
uv run python -m unittest test.test_image_tasks_api test.test_image_task_service test.test_image_conversation_service
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/forever/workspace/HappyImage/happyimage-api
git add api/image_tasks.py api/image_inputs.py services/image_task_service.py test/test_image_tasks_api.py test/test_image_task_service.py
git commit -m "feat: link image tasks to conversation results"
```

---

### Task 4: Frontend API Helpers

**Files:**
- Modify: `/Users/forever/workspace/HappyImage/happyimage-web/src/lib/api.ts`

- [ ] **Step 1: Add API types**

In `/Users/forever/workspace/HappyImage/happyimage-web/src/lib/api.ts`, import the shared types:

```ts
import type { ImageConversation, ImageTurn } from "@/store/image-conversations";
```

If this creates a circular type-only import warning, keep it because TypeScript erases type-only imports.

Add response/payload types near `ImageTask`:

```ts
type ImageConversationListResponse = {
  items: ImageConversation[];
};

type ImageConversationItemResponse = {
  item: ImageConversation;
};

export type ImageConversationTurnPayload = ImageTurn;
export type ImageConversationTurnPatch = Partial<Pick<ImageTurn, "prompt" | "status" | "error" | "promptDeleted" | "resultsDeleted">>;
export type ImageConversationResultPatch = {
  taskId?: string;
  status?: "loading" | "success" | "error";
  taskStatus?: "queued" | "running" | null;
  progress?: string | null;
  url?: string | null;
  revised_prompt?: string | null;
  error?: string | null;
  durationMs?: number | null;
  feedback?: ImageFeedbackSummary | null;
};
```

- [ ] **Step 2: Add API helper functions**

In `/Users/forever/workspace/HappyImage/happyimage-web/src/lib/api.ts`, add:

```ts
export async function fetchImageConversations() {
  return httpRequest<ImageConversationListResponse>(`/api/image-conversations?_t=${Date.now()}`, {
    redirectOnUnauthorized: false,
  });
}

export async function upsertImageConversation(conversationId: string, title: string) {
  return httpRequest<ImageConversationItemResponse>(`/api/image-conversations/${encodeURIComponent(conversationId)}`, {
    method: "PUT",
    redirectOnUnauthorized: false,
    body: { title },
  });
}

export async function createImageConversationTurn(conversationId: string, turn: ImageConversationTurnPayload) {
  return httpRequest<ImageConversationItemResponse>(`/api/image-conversations/${encodeURIComponent(conversationId)}/turns`, {
    method: "POST",
    redirectOnUnauthorized: false,
    body: turn,
  });
}

export async function updateImageConversationTurn(conversationId: string, turnId: string, updates: ImageConversationTurnPatch) {
  return httpRequest<ImageConversationItemResponse>(
    `/api/image-conversations/${encodeURIComponent(conversationId)}/turns/${encodeURIComponent(turnId)}`,
    {
      method: "PATCH",
      redirectOnUnauthorized: false,
      body: updates,
    },
  );
}

export async function updateImageConversationResult(conversationId: string, imageId: string, updates: ImageConversationResultPatch) {
  return httpRequest<ImageConversationItemResponse>(
    `/api/image-conversations/${encodeURIComponent(conversationId)}/results/${encodeURIComponent(imageId)}`,
    {
      method: "PATCH",
      redirectOnUnauthorized: false,
      body: updates,
    },
  );
}

export async function deleteServerImageConversation(conversationId: string) {
  return httpRequest<{ ok: boolean }>(`/api/image-conversations/${encodeURIComponent(conversationId)}`, {
    method: "DELETE",
    redirectOnUnauthorized: false,
  });
}
```

- [ ] **Step 3: Include client image ID in task metadata**

Update `createImageGenerationTask` and `createImageEditTask` metadata types:

```ts
metadata: { conversationId?: string; turnId?: string; imageId?: string } = {},
```

In generation body add:

```ts
...(metadata.imageId ? { client_image_id: metadata.imageId } : {}),
```

In edit form add:

```ts
if (metadata.imageId) {
  formData.append("client_image_id", metadata.imageId);
}
```

- [ ] **Step 4: Typecheck**

```bash
cd /Users/forever/workspace/HappyImage/happyimage-web
pnpm exec tsc --noEmit
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/forever/workspace/HappyImage/happyimage-web
git add src/lib/api.ts
git commit -m "feat: add image conversation api client"
```

---

### Task 5: Frontend Load Path Uses Server Conversations

**Files:**
- Modify: `/Users/forever/workspace/HappyImage/happyimage-web/src/app/image/page.tsx`

- [ ] **Step 1: Import server conversation helpers**

In `/Users/forever/workspace/HappyImage/happyimage-web/src/app/image/page.tsx`, add to the API import:

```ts
fetchImageConversations,
```

- [ ] **Step 2: Remove task-ID reconstruction from load path**

Remove these helper functions from `/Users/forever/workspace/HappyImage/happyimage-web/src/app/image/page.tsx` after server conversations are wired:

```ts
taskTimestamp
taskGroupKey
legacyTaskTurnKey
taskConversationKey
taskTurnKey
taskImageIndex
buildConversationsFromImageTasks
conversationLegacyTaskKey
mergeLegacyTaskConversations
restoreServerImageTaskHistory
```

In `recoverConversationHistory`, replace the end of the function:

```ts
const restored = await restoreServerImageTaskHistory(normalized, ownerId);
return syncConversationImageTasks(restored, ownerId);
```

with:

```ts
return syncConversationImageTasks(normalized, ownerId);
```

- [ ] **Step 3: Add server load helper**

Inside `ImagePageContent`, before `loadHistory`, add:

```ts
  const loadServerConversations = useCallback(async () => {
    if (isGuest) {
      return null;
    }
    try {
      const data = await fetchImageConversations();
      const items = sortImageConversations(data.items || []);
      await saveImageConversations(items, ownerId);
      return items;
    } catch {
      return null;
    }
  }, [isGuest, ownerId]);
```

- [ ] **Step 4: Prefer server conversations in `loadHistory`**

In `loadHistory`, replace:

```ts
const items = await listImageConversations(ownerId);
const normalizedItems = await recoverConversationHistory(items, ownerId);
```

with:

```ts
const cachedItems = await listImageConversations(ownerId);
const serverItems = await loadServerConversations();
const normalizedItems = serverItems ?? (await recoverConversationHistory(cachedItems, ownerId));
```

Add `loadServerConversations` to the `loadHistory` dependency array.

- [ ] **Step 5: Typecheck**

```bash
cd /Users/forever/workspace/HappyImage/happyimage-web
pnpm exec tsc --noEmit
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/forever/workspace/HappyImage/happyimage-web
git add src/app/image/page.tsx
git commit -m "feat: load image conversations from server"
```

---

### Task 6: Frontend Mutations Persist Server Conversations

**Files:**
- Modify: `/Users/forever/workspace/HappyImage/happyimage-web/src/app/image/page.tsx`

- [ ] **Step 1: Import mutation helpers**

Add to the API import:

```ts
createImageConversationTurn,
deleteServerImageConversation,
updateImageConversationResult,
updateImageConversationTurn,
upsertImageConversation,
```

- [ ] **Step 2: Persist conversation in `persistConversation`**

Replace `persistConversation` with:

```ts
  const persistConversation = async (conversation: ImageConversation) => {
    const nextConversations = sortImageConversations([
      conversation,
      ...conversationsRef.current.filter((item) => item.id !== conversation.id),
    ]);
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    await saveImageConversation(conversation, ownerId);
    if (!isGuest) {
      await upsertImageConversation(conversation.id, conversation.title);
    }
  };
```

- [ ] **Step 3: Persist turn before submitting tasks**

In `handleSubmit`, after `await persistConversation(baseConversation);` and before `void runConversationQueue(conversationId);`, add:

```ts
    if (!isGuest) {
      try {
        await createImageConversationTurn(conversationId, draftTurn);
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "保存会话轮次失败");
      }
    }
```

- [ ] **Step 4: Send image ID with task submissions**

In `runConversationQueue`, replace:

```ts
const taskMetadata = { conversationId, turnId: activeTurn.id };
```

with per-image metadata in both initial submit and missing resubmit maps:

```ts
const taskMetadata = { conversationId, turnId: activeTurn.id, imageId: image.id };
```

Use that inline inside each `map((image) => { ... })` block so `image.id` is available.

- [ ] **Step 5: Persist server result updates during polling**

Inside `applyTasks`, after `await updateConversation(...)`, add:

```ts
        await Promise.allSettled(
          tasks.map(async (task) => {
            const latestConversation = conversationsRef.current.find((conversation) => conversation.id === conversationId);
            const latestTurn = latestConversation?.turns.find((turn) => turn.id === activeTurn.id);
            const image = latestTurn?.images.find((candidate) => candidate.taskId === task.id);
            if (!image) {
              return;
            }
            await updateImageConversationResult(conversationId, image.id, {
              taskId: image.taskId,
              status: image.status,
              taskStatus: image.taskStatus ?? null,
              progress: image.progress ?? null,
              url: image.url ?? null,
              revised_prompt: image.revised_prompt ?? null,
              error: image.error ?? null,
              durationMs: image.durationMs ?? null,
              feedback: image.feedback ?? null,
            });
          }),
        );
```

- [ ] **Step 6: Persist delete/rename mutations**

In `handleDeleteConversation`, replace the server/local delete section:

```ts
await deleteImageConversation(id, ownerId);
```

with:

```ts
await deleteImageConversation(id, ownerId);
if (!isGuest) {
  await deleteServerImageConversation(id);
}
```

In `handleRenameConversation`, after local `renameImageConversation`, add:

```ts
if (!isGuest) {
  await upsertImageConversation(id, title);
}
```

In `handleDeleteTurnPart`, after `await persistConversation(nextConversation);`, add:

```ts
if (!isGuest) {
  await updateImageConversationTurn(conversationId, turnId, {
    prompt: part === "prompt" ? "" : undefined,
    promptDeleted: part === "prompt" ? true : undefined,
    resultsDeleted: part === "results" ? true : undefined,
    status: part === "results" ? "error" : undefined,
  });
}
```

- [ ] **Step 7: Persist feedback to server conversation result**

In `handleImageFeedback`, after successful `updateConversation` that applies backend task feedback, add:

```ts
await updateImageConversationResult(conversationId, imageId, { feedback });
```

- [ ] **Step 8: Typecheck and unit tests**

```bash
cd /Users/forever/workspace/HappyImage/happyimage-web
pnpm exec tsc --noEmit
pnpm test:unit -- --run
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
cd /Users/forever/workspace/HappyImage/happyimage-web
git add src/app/image/page.tsx
git commit -m "feat: persist image conversation mutations"
```

---

### Task 7: Full Verification and Cleanup

**Files:**
- Modify only if needed based on test failures:
  - `/Users/forever/workspace/HappyImage/happyimage-api/api/app.py`
  - `/Users/forever/workspace/HappyImage/happyimage-api/services/image_task_service.py`
  - `/Users/forever/workspace/HappyImage/happyimage-web/src/app/image/page.tsx`

- [ ] **Step 1: Run backend focused tests**

```bash
cd /Users/forever/workspace/HappyImage/happyimage-api
uv run python -m unittest \
  test.test_image_conversation_service \
  test.test_image_conversations_api \
  test.test_image_tasks_api \
  test.test_image_task_service
```

Expected: PASS.

- [ ] **Step 2: Run backend syntax check**

```bash
cd /Users/forever/workspace/HappyImage/happyimage-api
uv run python -m py_compile \
  api/image_conversations.py \
  api/image_tasks.py \
  api/image_inputs.py \
  services/image_conversation_store.py \
  services/image_conversation_service.py \
  services/image_task_service.py
```

Expected: PASS with no output.

- [ ] **Step 3: Run frontend checks**

```bash
cd /Users/forever/workspace/HappyImage/happyimage-web
pnpm exec tsc --noEmit
pnpm test:unit -- --run
pnpm build
```

Expected: all commands PASS.

- [ ] **Step 4: Manual browser verification**

Run the app using existing local dev setup:

```bash
cd /Users/forever/workspace/HappyImage/happyimage-web
pnpm dev
```

Expected: Next.js starts or reports an already-running dev server URL.

Manual scenario:

1. Log in as `user` in Chrome.
2. Create one new image conversation.
3. Add at least two turns to the same conversation.
4. Generate at least one successful image.
5. Open a fresh Chrome profile or incognito window.
6. Log in as the same `user`.
7. Open `/image`.
8. Verify exactly one conversation appears with both turns.
9. Open “我的图库” and verify successful results appear.

- [ ] **Step 5: Commit final cleanup**

If any verification fixes were required:

```bash
git status --short
git add api/image_conversations.py api/image_tasks.py api/image_inputs.py services/image_conversation_store.py services/image_conversation_service.py services/image_task_service.py
git add test/test_image_conversation_service.py test/test_image_conversations_api.py test/test_image_task_service.py test/test_image_tasks_api.py
git commit -m "fix: stabilize server image conversation persistence"
```

If no fixes were required, do not create an empty commit.

---

## Self-Review

Spec coverage:

- Server authoritative conversations: Tasks 1, 2, 5, 6.
- Async task execution preserved: Task 3 links tasks without replacing task execution.
- Fresh browser correctness: Tasks 5, 6, 7 manual scenario.
- No legacy task migration: Task 5 removes task-ID reconstruction from the load path.
- JSON/database compatibility: Task 1 store supports both modes.
- Error handling: Task 3 ignores missing conversation links during task execution; Task 6 preserves optimistic UI with user-facing save errors.
- Testing: Tasks 1, 2, 3, 6, 7 include focused backend/frontend checks.

Placeholder scan:

- No unresolved placeholders or unspecified implementation steps remain.
- All new functions and files referenced by later tasks are introduced in earlier tasks.

Type consistency:

- Backend uses `client_conversation_id`, `client_turn_id`, and `client_image_id`.
- Frontend metadata maps to `conversationId`, `turnId`, and `imageId`.
- Public conversation shape remains `ImageConversation` / `ImageTurn` from `src/store/image-conversations.ts`.
