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


def _conversation_key(owner_id: str, conversation_id: str) -> str:
    return f"{owner_id}:{conversation_id}"


def _positive_int(value: object, default: int = 1) -> int:
    try:
        return max(1, int(value or default))
    except (TypeError, ValueError):
        return default


def _normalize_image(value: dict[str, Any]) -> dict[str, Any]:
    item = {
        "id": _clean(value.get("id")),
        "taskId": _clean(value.get("taskId") or value.get("task_id")),
        "status": _clean(value.get("status"), "loading"),
    }
    for field in (
        "taskStatus",
        "progress",
        "url",
        "revised_prompt",
        "error",
        "durationMs",
        "feedback",
    ):
        if value.get(field) is not None:
            item[field] = value.get(field)
    return item


def _derive_turn_status(turn: dict[str, Any]) -> tuple[str, str]:
    images = [image for image in turn.get("images", []) if isinstance(image, dict)]
    if any(image.get("status") == "loading" for image in images):
        if any(image.get("taskStatus") == "running" for image in images):
            return "generating", ""
        return "queued", ""
    failures = [image for image in images if image.get("status") == "error"]
    if failures:
        return "error", f"{len(failures)} image result failed"
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

    def upsert_conversation(
        self,
        identity: dict[str, object],
        conversation_id: str,
        title: str = "",
    ) -> dict[str, Any]:
        owner = _owner_id(identity)
        normalized_id = _clean(conversation_id)
        if not normalized_id:
            raise ValueError("conversation_id is required")
        key = _conversation_key(owner, normalized_id)
        now = _now_iso()
        with self._lock:
            self._items = self._load_locked()
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
            self._save_locked({key})
            return self._public_conversation(item)

    def create_turn(
        self,
        identity: dict[str, object],
        conversation_id: str,
        turn: dict[str, Any],
    ) -> dict[str, Any]:
        owner = _owner_id(identity)
        key = _conversation_key(owner, _clean(conversation_id))
        now = _now_iso()
        with self._lock:
            self._items = self._load_locked()
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
                "count": _positive_int(turn.get("count"), len(images) or 1),
                "size": _clean(turn.get("size")),
                "ratio": _clean(turn.get("ratio"), "1:1"),
                "tier": _clean(turn.get("tier"), "1k"),
                "quality": _clean(turn.get("quality"), "auto"),
                "images": images,
                "createdAt": _clean(turn.get("createdAt"), now),
                "status": _clean(turn.get("status"), "queued"),
            }
            turns = [
                candidate
                for candidate in conversation.get("turns", [])
                if isinstance(candidate, dict) and candidate.get("id") != turn_id
            ]
            turns.append(next_turn)
            conversation["turns"] = turns
            conversation["updatedAt"] = now
            self._items[key] = conversation
            self._save_locked({key})
            return self._public_conversation(conversation)

    def update_turn(
        self,
        identity: dict[str, object],
        conversation_id: str,
        turn_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        owner = _owner_id(identity)
        key = _conversation_key(owner, _clean(conversation_id))
        now = _now_iso()
        with self._lock:
            self._items = self._load_locked()
            conversation = self._items.get(key)
            if conversation is None or conversation.get("deletedAt"):
                raise ValueError("conversation not found")
            found = False
            turns = []
            for turn in conversation.get("turns", []):
                if not isinstance(turn, dict) or turn.get("id") != turn_id:
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
            self._items[key] = conversation
            self._save_locked({key})
            return self._public_conversation(conversation)

    def update_result(
        self,
        identity: dict[str, object],
        conversation_id: str,
        image_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        owner = _owner_id(identity)
        key = _conversation_key(owner, _clean(conversation_id))
        now = _now_iso()
        with self._lock:
            self._items = self._load_locked()
            conversation = self._items.get(key)
            if conversation is None or conversation.get("deletedAt"):
                raise ValueError("conversation not found")
            found = False
            next_turns = []
            for turn in conversation.get("turns", []):
                if not isinstance(turn, dict):
                    next_turns.append(turn)
                    continue
                next_images = []
                turn_changed = False
                for image in turn.get("images", []):
                    if not isinstance(image, dict) or image.get("id") != image_id:
                        next_images.append(image)
                        continue
                    found = True
                    turn_changed = True
                    next_image = dict(image)
                    for field in (
                        "taskId",
                        "status",
                        "taskStatus",
                        "progress",
                        "url",
                        "revised_prompt",
                        "error",
                        "durationMs",
                        "feedback",
                    ):
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
            self._items[key] = conversation
            self._save_locked({key})
            return self._public_conversation(conversation)

    def delete_conversation(self, identity: dict[str, object], conversation_id: str) -> dict[str, Any]:
        owner = _owner_id(identity)
        key = _conversation_key(owner, _clean(conversation_id))
        now = _now_iso()
        with self._lock:
            self._items = self._load_locked()
            conversation = self._items.get(key)
            if conversation is None:
                raise ValueError("conversation not found")
            conversation["deletedAt"] = now
            conversation["updatedAt"] = now
            self._items[key] = conversation
            self._save_locked({key})
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
            items[_conversation_key(owner, conversation_id)] = item
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

    def _save_locked(self, changed_keys: set[str]) -> None:
        changed_items = [self._items[key] for key in changed_keys if key in self._items]
        self.store.save_changed_conversations(changed_items)
        self._items = self._load_locked()


image_conversation_service = ImageConversationService(DATA_DIR / "image_conversations.json")
