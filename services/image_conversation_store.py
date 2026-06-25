from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import fcntl

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

    def save_changed_conversations(self, conversations: list[dict[str, Any]]) -> None:
        ...


class JSONImageConversationStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_conversations(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            return self._read_unlocked()
        except (OSError, json.JSONDecodeError, ValueError):
            return []

    def save_conversations(self, conversations: list[dict[str, Any]]) -> None:
        self.save_changed_conversations(conversations)

    def save_changed_conversations(self, conversations: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with lock_path.open("w", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            current = {
                self._conversation_key(item): item
                for item in self._read_unlocked()
                if isinstance(item, dict) and self._conversation_key(item)
            }
            for item in conversations:
                key = self._conversation_key(item) if isinstance(item, dict) else ""
                if key:
                    current[key] = item
            items = sorted(current.values(), key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
            self._write_unlocked(items)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        items = raw.get("conversations") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            raise ValueError("image conversations JSON must contain a conversations list")
        return items

    def _write_unlocked(self, conversations: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.{uuid4().hex}.tmp")
        tmp_path.write_text(
            json.dumps({"conversations": conversations}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self.path)

    def _conversation_key(self, item: dict[str, Any]) -> str:
        owner = str(item.get("ownerId") or item.get("owner_id") or "").strip()
        conversation_id = str(item.get("id") or "").strip()
        return f"{owner}:{conversation_id}" if owner and conversation_id else ""


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
        self.engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        ImageConversationBase.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def load_conversations(self) -> list[dict[str, Any]]:
        session = self.Session()
        try:
            rows = session.query(ImageConversationModel).order_by(ImageConversationModel.updated_at.desc()).all()
            items: list[dict[str, Any]] = []
            for row in rows:
                try:
                    item = json.loads(row.data)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    items.append(item)
            return items
        finally:
            session.close()

    def save_conversations(self, conversations: list[dict[str, Any]]) -> None:
        self.save_changed_conversations(conversations)

    def save_changed_conversations(self, conversations: list[dict[str, Any]]) -> None:
        session = self.Session()
        try:
            for item in conversations:
                if not isinstance(item, dict):
                    continue
                owner = str(item.get("ownerId") or item.get("owner_id") or "").strip()
                conversation_id = str(item.get("id") or "").strip()
                if not owner or not conversation_id:
                    continue
                conversation_key = f"{owner}:{conversation_id}"
                data = json.dumps(item, ensure_ascii=False)
                updated_at = str(item.get("updatedAt") or item.get("updated_at") or "")
                row = (
                    session.query(ImageConversationModel)
                    .filter(ImageConversationModel.conversation_key == conversation_key)
                    .one_or_none()
                )
                if row is None:
                    session.add(
                        ImageConversationModel(
                            conversation_key=conversation_key,
                            owner_id=owner,
                            conversation_id=conversation_id,
                            updated_at=updated_at,
                            data=data,
                        )
                    )
                else:
                    row.owner_id = owner
                    row.conversation_id = conversation_id
                    row.updated_at = updated_at
                    row.data = data
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def create_image_conversation_store(path: Path) -> ImageConversationStore:
    backend_type = os.getenv("STORAGE_BACKEND", "json").lower().strip()
    if backend_type in ("sqlite", "postgres", "postgresql", "mysql", "database"):
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            database_url = f"sqlite:///{DATA_DIR / 'accounts.db'}"
        print(f"[image-conversations] Using database storage: {_mask_password(database_url)}")
        return DatabaseImageConversationStore(database_url)
    print(f"[image-conversations] Using JSON storage: {path}")
    return JSONImageConversationStore(path)
