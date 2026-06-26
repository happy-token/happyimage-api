from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from services.storage.base import StorageBackend

_AUTH_KEY_FILE_LOCKS: dict[str, Lock] = {}
_AUTH_KEY_FILE_LOCKS_GUARD = Lock()


def _auth_key_file_lock(path: Path) -> Lock:
    key = str(path.resolve())
    with _AUTH_KEY_FILE_LOCKS_GUARD:
        lock = _AUTH_KEY_FILE_LOCKS.get(key)
        if lock is None:
            lock = Lock()
            _AUTH_KEY_FILE_LOCKS[key] = lock
        return lock


class JSONStorageBackend(StorageBackend):
    """本地 JSON 文件存储后端"""

    def __init__(
        self,
        file_path: Path,
        auth_keys_path: Path | None = None,
        runtime_config_path: Path | None = None,
    ):
        self.file_path = file_path
        self.auth_keys_path = auth_keys_path or file_path.with_name("auth_keys.json")
        self.runtime_config_path = runtime_config_path or file_path.with_name("runtime_config.json")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.auth_keys_path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime_config_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _load_json_list(file_path: Path) -> list[dict[str, Any]]:
        if not file_path.exists():
            return []
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, Exception):
            return []

    @staticmethod
    def _save_json_list(file_path: Path, items: list[dict[str, Any]]) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def load_accounts(self) -> list[dict[str, Any]]:
        """从 JSON 文件加载账号数据"""
        return self._load_json_list(self.file_path)

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        """保存账号数据到 JSON 文件"""
        self._save_json_list(self.file_path, accounts)

    def load_auth_keys(self) -> list[dict[str, Any]]:
        """从 JSON 文件加载鉴权密钥数据"""
        if not self.auth_keys_path.exists():
            return []
        try:
            data = json.loads(self.auth_keys_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            return []
        if isinstance(data, dict):
            data = data.get("items")
        return data if isinstance(data, list) else []

    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        """保存鉴权密钥数据到 JSON 文件"""
        self.auth_keys_path.parent.mkdir(parents=True, exist_ok=True)
        self.auth_keys_path.write_text(
            json.dumps({"items": auth_keys}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def create_first_auth_key(self, role: str, item: dict[str, Any]) -> bool:
        normalized_role = str(role or "").strip()
        if not normalized_role:
            return False
        with _auth_key_file_lock(self.auth_keys_path):
            auth_keys = self.load_auth_keys()
            if any(key.get("role") == normalized_role for key in auth_keys):
                return False
            auth_keys.append(dict(item))
            self.save_auth_keys(auth_keys)
            return True

    def delete_first_auth_key(
        self, role: str, key_id: str, key_hash: str
    ) -> bool:
        with _auth_key_file_lock(self.auth_keys_path):
            return super().delete_first_auth_key(role, key_id, key_hash)

    def load_runtime_config(self) -> dict[str, Any]:
        if not self.runtime_config_path.exists():
            return {}
        data = json.loads(self.runtime_config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("runtime config must be a JSON object")
        return data

    def runtime_config_exists(self) -> bool:
        return self.runtime_config_path.exists()

    def save_runtime_config(self, config: dict[str, Any]) -> None:
        self.runtime_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime_config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def health_check(self) -> dict[str, Any]:
        """健康检查"""
        try:
            # 检查文件是否可读写
            if self.file_path.exists():
                self.file_path.read_text(encoding="utf-8")
            return {
                "status": "healthy",
                "backend": "json",
                "file_exists": self.file_path.exists(),
                "file_path": str(self.file_path),
                "auth_keys_file_exists": self.auth_keys_path.exists(),
                "auth_keys_file_path": str(self.auth_keys_path),
                "runtime_config_file_exists": self.runtime_config_path.exists(),
                "runtime_config_file_path": str(self.runtime_config_path),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "backend": "json",
                "error": str(e),
            }

    def get_backend_info(self) -> dict[str, Any]:
        """获取存储后端信息"""
        return {
            "type": "json",
            "description": "本地 JSON 文件存储",
            "file_path": str(self.file_path),
            "file_exists": self.file_path.exists(),
            "auth_keys_file_path": str(self.auth_keys_path),
            "auth_keys_file_exists": self.auth_keys_path.exists(),
            "runtime_config_file_path": str(self.runtime_config_path),
            "runtime_config_file_exists": self.runtime_config_path.exists(),
        }
