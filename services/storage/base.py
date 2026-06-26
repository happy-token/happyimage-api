from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StorageBackend(ABC):
    """抽象存储后端基类"""

    @abstractmethod
    def load_accounts(self) -> list[dict[str, Any]]:
        """加载所有账号数据"""
        pass

    @abstractmethod
    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        """保存所有账号数据"""
        pass

    @abstractmethod
    def load_auth_keys(self) -> list[dict[str, Any]]:
        """加载所有鉴权密钥数据"""
        pass

    @abstractmethod
    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        """保存所有鉴权密钥数据"""
        pass

    def create_first_auth_key(self, role: str, item: dict[str, Any]) -> bool:
        """Create the first auth key for a role when possible."""
        normalized_role = str(role or "").strip()
        if not normalized_role:
            return False
        auth_keys = self.load_auth_keys()
        if any(key.get("role") == normalized_role for key in auth_keys):
            return False
        auth_keys.append(dict(item))
        self.save_auth_keys(auth_keys)
        return True

    def delete_first_auth_key(
        self, role: str, key_id: str, key_hash: str
    ) -> bool:
        """Delete a first auth key only when id, role, and hash match."""
        normalized_role = str(role or "").strip()
        normalized_id = str(key_id or "").strip()
        normalized_hash = str(key_hash or "").strip()
        if not normalized_role or not normalized_id or not normalized_hash:
            return False
        auth_keys = self.load_auth_keys()
        next_keys = [
            item
            for item in auth_keys
            if not (
                item.get("id") == normalized_id
                and item.get("role") == normalized_role
                and item.get("key_hash") == normalized_hash
            )
        ]
        if len(next_keys) == len(auth_keys):
            return False
        self.save_auth_keys(next_keys)
        return True

    @abstractmethod
    def load_runtime_config(self) -> dict[str, Any]:
        """Load admin-managed runtime configuration."""
        pass

    @abstractmethod
    def runtime_config_exists(self) -> bool:
        """Return whether admin-managed runtime configuration has been persisted."""
        pass

    @abstractmethod
    def save_runtime_config(self, config: dict[str, Any]) -> None:
        """Persist admin-managed runtime configuration."""
        pass

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """健康检查，返回存储后端状态"""
        pass

    @abstractmethod
    def get_backend_info(self) -> dict[str, Any]:
        """获取存储后端信息"""
        pass
