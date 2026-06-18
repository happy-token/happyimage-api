from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from services.config import DATA_DIR

VALID_STATUSES = {"draft", "pending_review", "approved", "rejected"}
REQUIRED_FIELDS = (
    "image_url",
    "conversation_id",
    "turn_id",
    "image_id",
    "original_prompt",
    "share_prompt",
    "title",
)


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _next_iso(previous: object = None) -> str:
    now = datetime.now()
    previous_text = _clean(previous)
    if previous_text:
        try:
            previous_dt = datetime.strptime(previous_text, "%Y-%m-%d %H:%M:%S.%f")
            if now <= previous_dt:
                now = previous_dt + timedelta(microseconds=1)
        except ValueError:
            pass
    return now.strftime("%Y-%m-%d %H:%M:%S.%f")


def _clean(value: object, default: str = "") -> str:
    return str(value or default).strip()


def _owner_id(identity: dict[str, object]) -> str:
    return _clean(identity.get("id")) or "anonymous"


def _normalize_tags(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [tag for tag in (_clean(item) for item in value) if tag]


class ShareDraftService:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._drafts: dict[str, dict[str, Any]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._drafts = self._load_locked()

    def save_draft(self, identity: dict[str, object], payload: dict[str, Any]) -> dict[str, Any]:
        owner = _owner_id(identity)
        image_id = _clean(payload.get("image_id"))
        with self._lock:
            draft_id = _clean(payload.get("id"))
            has_explicit_id = bool(draft_id)
            existing = self._drafts.get(_draft_key(owner, draft_id)) if has_explicit_id else None
            if not has_explicit_id and image_id:
                existing = self._find_by_owner_image_locked(owner, image_id)
            if not draft_id:
                draft_id = _clean((existing or {}).get("id")) or uuid.uuid4().hex

            updated_at = _next_iso((existing or {}).get("updated_at"))
            item = {
                "id": draft_id,
                "owner_id": owner,
                "source": "user_gallery",
                "image_url": _clean(payload.get("image_url")),
                "conversation_id": _clean(payload.get("conversation_id")),
                "turn_id": _clean(payload.get("turn_id")),
                "image_id": image_id,
                "original_prompt": _clean(payload.get("original_prompt")),
                "conversation_summary": _clean(payload.get("conversation_summary")),
                "share_prompt": _clean(payload.get("share_prompt")),
                "title": _clean(payload.get("title")),
                "category": _clean(payload.get("category")) or None,
                "tags": _normalize_tags(payload.get("tags")),
                "status": _normalize_status(payload.get("status")),
                "created_at": _clean((existing or {}).get("created_at")) or updated_at,
                "updated_at": updated_at,
            }
            self._validate(item)
            self._drafts[_draft_key(owner, draft_id)] = item
            self._save_locked()
            return _public_item(item)

    def list_drafts(self, identity: dict[str, object]) -> dict[str, list[dict[str, Any]]]:
        owner = _owner_id(identity)
        with self._lock:
            items = [_public_item(item) for item in self._drafts.values() if item.get("owner_id") == owner]
        items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return {"items": items}

    def _find_by_owner_image_locked(self, owner: str, image_id: str) -> dict[str, Any] | None:
        for item in self._drafts.values():
            if item.get("owner_id") == owner and item.get("image_id") == image_id:
                return item
        return None

    def _validate(self, item: dict[str, Any]) -> None:
        missing = [field for field in REQUIRED_FIELDS if not item.get(field)]
        if missing:
            raise ValueError(f"missing required fields: {', '.join(missing)}")

    def _load_locked(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        raw_items = raw.get("items") if isinstance(raw, dict) else raw
        if not isinstance(raw_items, list):
            return {}

        drafts: dict[str, dict[str, Any]] = {}
        for raw_item in raw_items:
            item = self._normalize_loaded_item(raw_item)
            if item is not None:
                drafts[_draft_key(item["owner_id"], item["id"])] = item
        return drafts

    def _normalize_loaded_item(self, raw_item: object) -> dict[str, Any] | None:
        if not isinstance(raw_item, dict):
            return None
        draft_id = _clean(raw_item.get("id"))
        owner = _clean(raw_item.get("owner_id"))
        if not draft_id or not owner:
            return None
        item = {
            "id": draft_id,
            "owner_id": owner,
            "source": "user_gallery",
            "image_url": _clean(raw_item.get("image_url")),
            "conversation_id": _clean(raw_item.get("conversation_id")),
            "turn_id": _clean(raw_item.get("turn_id")),
            "image_id": _clean(raw_item.get("image_id")),
            "original_prompt": _clean(raw_item.get("original_prompt")),
            "conversation_summary": _clean(raw_item.get("conversation_summary")),
            "share_prompt": _clean(raw_item.get("share_prompt")),
            "title": _clean(raw_item.get("title")),
            "category": _clean(raw_item.get("category")) or None,
            "tags": _normalize_tags(raw_item.get("tags")),
            "status": _normalize_status(raw_item.get("status")),
            "created_at": _clean(raw_item.get("created_at"), _now_iso()),
            "updated_at": _clean(raw_item.get("updated_at"), _clean(raw_item.get("created_at"), _now_iso())),
        }
        try:
            self._validate(item)
        except ValueError:
            return None
        return item

    def _save_locked(self) -> None:
        items = sorted(self._drafts.values(), key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)


def _draft_key(owner: str, draft_id: str) -> str:
    return f"{owner}:{draft_id}"


def _normalize_status(value: object) -> str:
    status = _clean(value, "draft")
    return status if status in VALID_STATUSES else "draft"


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    return dict(item)


share_draft_service = ShareDraftService(DATA_DIR / "share_drafts.json")
