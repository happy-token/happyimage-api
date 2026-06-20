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


class ImageTaskStore(Protocol):
    def load_tasks(self) -> list[dict[str, Any]]:
        ...

    def save_tasks(self, tasks: list[dict[str, Any]]) -> None:
        ...


class JSONImageTaskStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_tasks(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        raw_items = raw.get("tasks") if isinstance(raw, dict) else raw
        return raw_items if isinstance(raw_items, list) else []

    def save_tasks(self, tasks: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self.path)


ImageTaskBase = declarative_base()


class ImageTaskModel(ImageTaskBase):
    __tablename__ = "image_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_key = Column(String(512), unique=True, nullable=False, index=True)
    owner_id = Column(String(255), nullable=False, index=True)
    task_id = Column(String(255), nullable=False, index=True)
    updated_at = Column(String(64), nullable=False, index=True)
    data = Column(Text, nullable=False)


class DatabaseImageTaskStore:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        ImageTaskBase.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def load_tasks(self) -> list[dict[str, Any]]:
        session = self.Session()
        try:
            items: list[dict[str, Any]] = []
            rows = session.query(ImageTaskModel).order_by(ImageTaskModel.updated_at.desc()).all()
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

    def save_tasks(self, tasks: list[dict[str, Any]]) -> None:
        session = self.Session()
        try:
            session.query(ImageTaskModel).delete()
            for item in tasks:
                if not isinstance(item, dict):
                    continue
                owner = str(item.get("owner_id") or "").strip()
                task_id = str(item.get("id") or "").strip()
                if not owner or not task_id:
                    continue
                session.add(
                    ImageTaskModel(
                        task_key=f"{owner}:{task_id}",
                        owner_id=owner,
                        task_id=task_id,
                        updated_at=str(item.get("updated_at") or ""),
                        data=json.dumps(item, ensure_ascii=False),
                    )
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def create_image_task_store(path: Path) -> ImageTaskStore:
    backend_type = os.getenv("STORAGE_BACKEND", "json").lower().strip()
    if backend_type in ("sqlite", "postgres", "postgresql", "mysql", "database"):
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            database_url = f"sqlite:///{DATA_DIR / 'accounts.db'}"
        print(f"[image-tasks] Using database storage: {_mask_password(database_url)}")
        return DatabaseImageTaskStore(database_url)
    print(f"[image-tasks] Using JSON storage: {path}")
    return JSONImageTaskStore(path)
