from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone
from threading import Lock
from typing import Literal

from services.config import config
from services.storage.base import StorageBackend

AuthRole = Literal["admin", "user"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(self, storage: StorageBackend):
        self.storage = storage
        self._lock = Lock()
        self._items = self._load()
        self._last_used_flush_at: dict[str, datetime] = {}

    @staticmethod
    def _clean(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _default_name(role: object) -> str:
        return "管理员密钥" if str(role or "").strip().lower() == "admin" else "普通用户"

    def _normalize_model_providers(
        self,
        value: object,
        *,
        fallback_provider: str = "",
        fallback_base_url: str = "",
        fallback_api_key: str = "",
        existing: object = None,
    ) -> list[dict[str, object]]:
        existing_keys: dict[str, str] = {}
        if isinstance(existing, list):
            for item in existing:
                if not isinstance(item, dict):
                    continue
                provider_id = self._clean(item.get("id"))
                if provider_id:
                    existing_keys[provider_id] = self._clean(item.get("api_key"))

        providers: list[dict[str, object]] = []
        source = value if isinstance(value, list) else []
        for index, raw_provider in enumerate(source):
            if not isinstance(raw_provider, dict):
                continue
            provider_id = self._clean(raw_provider.get("id")) or uuid.uuid4().hex[:12]
            provider_type = self._clean(raw_provider.get("type") or raw_provider.get("model_provider"))[:32] or "newapi"
            protocol = self._clean(raw_provider.get("protocol"))[:32] or "openai"
            base_url = self._clean(raw_provider.get("base_url") or raw_provider.get("model_base_url")).rstrip("/")[:512]
            api_key = self._clean(raw_provider.get("api_key") or raw_provider.get("model_api_key"))
            raw_models = raw_provider.get("models")
            models = []
            if isinstance(raw_models, list):
                seen_models: set[str] = set()
                for raw_model in raw_models:
                    model = self._clean(raw_model)[:100]
                    if model and model not in seen_models:
                        models.append(model)
                        seen_models.add(model)
            if not api_key and bool(raw_provider.get("api_key_configured")):
                api_key = existing_keys.get(provider_id, "")
            if not base_url:
                continue
            providers.append(
                {
                    "id": provider_id[:64],
                    "type": provider_type,
                    "protocol": protocol,
                    "base_url": base_url,
                    "models": models,
                    "api_key": api_key,
                    "selected": bool(raw_provider.get("selected")),
                }
            )

        if not providers and (fallback_base_url or fallback_api_key):
            providers.append(
                {
                    "id": "default",
                    "type": (fallback_provider[:32] or "newapi"),
                    "protocol": "openai",
                    "base_url": fallback_base_url[:512],
                    "models": [],
                    "api_key": fallback_api_key,
                    "selected": True,
                }
            )

        first_selected_index = next((index for index, item in enumerate(providers) if bool(item.get("selected"))), 0)
        return [{**item, "selected": index == first_selected_index} for index, item in enumerate(providers)]

    @staticmethod
    def _selected_model_provider(providers: object) -> dict[str, object]:
        if not isinstance(providers, list):
            return {}
        for provider in providers:
            if isinstance(provider, dict) and bool(provider.get("selected")):
                return provider
        for provider in providers:
            if isinstance(provider, dict):
                return provider
        return {}

    @classmethod
    def _public_model_providers(cls, providers: object) -> list[dict[str, object]]:
        if not isinstance(providers, list):
            return []
        public: list[dict[str, object]] = []
        for provider in providers:
            if not isinstance(provider, dict):
                continue
            public.append(
                {
                    "id": provider.get("id") or "",
                    "type": provider.get("type") or "newapi",
                    "protocol": provider.get("protocol") or "openai",
                    "base_url": provider.get("base_url") or "",
                    "models": provider.get("models") if isinstance(provider.get("models"), list) else [],
                    "api_key_configured": bool(provider.get("api_key")),
                    "selected": bool(provider.get("selected")),
                }
            )
        return public

    def _sync_legacy_model_provider_fields(self, item: dict[str, object]) -> dict[str, object]:
        providers = self._normalize_model_providers(
            item.get("model_providers"),
            fallback_provider=self._clean(item.get("model_provider")),
            fallback_base_url=self._clean(item.get("model_base_url")).rstrip("/"),
            fallback_api_key=self._clean(item.get("model_api_key")),
            existing=item.get("model_providers"),
        )
        selected_provider = self._selected_model_provider(providers)
        item["model_providers"] = providers
        item["model_provider"] = selected_provider.get("type") or ""
        item["model_base_url"] = selected_provider.get("base_url") or ""
        item["model_api_key"] = selected_provider.get("api_key") or ""
        return item

    def _normalize_item(self, raw: object) -> dict[str, object] | None:
        if not isinstance(raw, dict):
            return None
        role = self._clean(raw.get("role")).lower()
        if role not in {"admin", "user"}:
            return None
        key_hash = self._clean(raw.get("key_hash"))
        # OIDC-created users have auth_provider/auth_subject instead of key_hash
        auth_provider = self._clean(raw.get("auth_provider"))
        auth_subject = self._clean(raw.get("auth_subject"))
        is_oidc_user = bool(auth_provider) and bool(auth_subject)
        if not key_hash and not is_oidc_user:
            return None
        item_id = self._clean(raw.get("id")) or uuid.uuid4().hex[:12]
        name = self._clean(raw.get("name")) or self._default_name(role)
        created_at = self._clean(raw.get("created_at")) or _now_iso()
        last_used_at = self._clean(raw.get("last_used_at")) or None
        watermark_label = self._clean(raw.get("watermark_label"))
        watermark_unlocked = bool(raw.get("watermark_unlocked", False))
        model_provider = self._clean(raw.get("model_provider"))
        model_base_url = self._clean(raw.get("model_base_url")).rstrip("/")
        model_api_key = self._clean(raw.get("model_api_key"))
        email = self._clean(raw.get("email")) or None
        preferences = raw.get("preferences") if isinstance(raw.get("preferences"), dict) else {}
        model_providers = self._normalize_model_providers(
            raw.get("model_providers"),
            fallback_provider=model_provider,
            fallback_base_url=model_base_url,
            fallback_api_key=model_api_key,
        )
        selected_provider = self._selected_model_provider(model_providers)
        item: dict[str, object] = {
            "id": item_id,
            "name": name,
            "role": role,
            "key_hash": key_hash,
            "enabled": bool(raw.get("enabled", True)),
            "watermark_label": watermark_label,
            "watermark_unlocked": watermark_unlocked,
            "model_provider": selected_provider.get("type") or model_provider,
            "model_base_url": selected_provider.get("base_url") or model_base_url,
            "model_api_key": selected_provider.get("api_key") or model_api_key,
            "model_providers": model_providers,
            "preferences": dict(preferences),
            "created_at": created_at,
            "last_used_at": last_used_at,
        }
        if auth_provider:
            item["auth_provider"] = auth_provider
        if auth_subject:
            item["auth_subject"] = auth_subject
        if email:
            item["email"] = email
        return item

    def _load(self) -> list[dict[str, object]]:
        try:
            items = self.storage.load_auth_keys()
        except Exception:
            return []
        if not isinstance(items, list):
            return []
        return [normalized for item in items if (normalized := self._normalize_item(item)) is not None]

    def _save(self) -> None:
        self.storage.save_auth_keys(self._items)

    def _reload_locked(self) -> None:
        self._items = self._load()

    @staticmethod
    def _public_item(item: dict[str, object]) -> dict[str, object]:
        providers = AuthService._public_model_providers(item.get("model_providers"))
        public: dict[str, object] = {
            "id": item.get("id"),
            "name": item.get("name"),
            "role": item.get("role"),
            "enabled": bool(item.get("enabled", True)),
            "watermark_label": item.get("watermark_label") or "",
            "watermark_unlocked": bool(item.get("watermark_unlocked", False)),
            "model_provider": item.get("model_provider") or "",
            "model_base_url": item.get("model_base_url") or "",
            "model_api_key_configured": bool(item.get("model_api_key")),
            "model_providers": providers,
            "preferences": item.get("preferences") if isinstance(item.get("preferences"), dict) else {},
            "created_at": item.get("created_at"),
            "last_used_at": item.get("last_used_at"),
        }
        auth_provider = item.get("auth_provider")
        if auth_provider:
            public["auth_provider"] = auth_provider
        auth_subject = item.get("auth_subject")
        if auth_subject:
            public["auth_subject"] = auth_subject
        email = item.get("email")
        if email:
            public["email"] = email
        return public

    def list_keys(self, role: AuthRole | None = None) -> list[dict[str, object]]:
        with self._lock:
            self._reload_locked()
            items = [item for item in self._items if role is None or item.get("role") == role]
            return [self._public_item(item) for item in items]

    def get_key(self, key_id: str, *, role: AuthRole | None = None) -> dict[str, object] | None:
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return None
        with self._lock:
            self._reload_locked()
            for item in self._items:
                if item.get("id") != normalized_id:
                    continue
                if role is not None and item.get("role") != role:
                    return None
                return self._public_item(item)
        return None

    def get_model_gateway_config(self, key_id: str) -> dict[str, object]:
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return {}
        with self._lock:
            self._reload_locked()
            for item in self._items:
                if item.get("id") != normalized_id:
                    continue
                selected_provider = self._selected_model_provider(item.get("model_providers"))
                return {
                    "model_provider": selected_provider.get("type") or item.get("model_provider") or "",
                    "model_base_url": selected_provider.get("base_url") or item.get("model_base_url") or "",
                    "model_api_key": selected_provider.get("api_key") or item.get("model_api_key") or "",
                }
        return {}

    def _has_key_hash_locked(self, key_hash: str, *, exclude_id: str = "") -> bool:
        for item in self._items:
            item_id = self._clean(item.get("id"))
            if exclude_id and item_id == exclude_id:
                continue
            stored_hash = self._clean(item.get("key_hash"))
            if stored_hash and hmac.compare_digest(stored_hash, key_hash):
                return True
        return False

    def _build_key_hash_locked(self, raw_key: str, *, exclude_id: str = "") -> str:
        candidate = self._clean(raw_key)
        if not candidate:
            raise ValueError("请输入新的专用密钥")
        key_hash = _hash_key(candidate)
        if self._has_key_hash_locked(key_hash, exclude_id=exclude_id):
            raise ValueError("这个专用密钥已经存在，请换一个新的密钥")
        return key_hash

    def _has_name_locked(self, name: str, *, role: AuthRole | None = None, exclude_id: str = "") -> bool:
        candidate = self._clean(name)
        if not candidate:
            return False
        for item in self._items:
            item_id = self._clean(item.get("id"))
            if exclude_id and item_id == exclude_id:
                continue
            if role is not None and item.get("role") != role:
                continue
            if self._clean(item.get("name")) == candidate:
                return True
        return False

    def _build_default_name_locked(self, role: AuthRole, *, exclude_id: str = "") -> str:
        base_name = self._default_name(role)
        if not self._has_name_locked(base_name, role=role, exclude_id=exclude_id):
            return base_name
        suffix = 2
        while True:
            candidate = f"{base_name} {suffix}"
            if not self._has_name_locked(candidate, role=role, exclude_id=exclude_id):
                return candidate
            suffix += 1

    def _build_name_locked(self, name: str, *, role: AuthRole, exclude_id: str = "") -> str:
        candidate = self._clean(name)
        if not candidate:
            return self._build_default_name_locked(role, exclude_id=exclude_id)
        if self._has_name_locked(candidate, role=role, exclude_id=exclude_id):
            raise ValueError("这个名称已经在使用中了，换一个更容易区分的名称吧")
        return candidate

    def create_key(
        self,
        *,
        role: AuthRole,
        name: str = "",
        watermark_label: str = "",
        watermark_unlocked: bool = False,
    ) -> tuple[dict[str, object], str]:
        with self._lock:
            self._reload_locked()
            normalized_name = self._build_name_locked(name, role=role)
            while True:
                raw_key = f"sk-{secrets.token_urlsafe(24)}"
                try:
                    key_hash = self._build_key_hash_locked(raw_key)
                    break
                except ValueError:
                    continue
            item = {
                "id": uuid.uuid4().hex[:12],
                "name": normalized_name,
                "role": role,
                "key_hash": key_hash,
                "enabled": True,
                "watermark_label": self._clean(watermark_label),
                "watermark_unlocked": bool(watermark_unlocked),
                "created_at": _now_iso(),
                "last_used_at": None,
            }
            self._items.append(item)
            self._save()
            return self._public_item(item), raw_key

    def create_key_with_value(
        self,
        *,
        role: AuthRole,
        name: str = "",
        key: str = "",
        watermark_label: str = "",
        watermark_unlocked: bool = False,
    ) -> dict[str, object]:
        with self._lock:
            self._reload_locked()
            normalized_name = self._build_name_locked(name, role=role)
            key_hash = self._build_key_hash_locked(key)
            item = {
                "id": uuid.uuid4().hex[:12],
                "name": normalized_name,
                "role": role,
                "key_hash": key_hash,
                "enabled": True,
                "watermark_label": self._clean(watermark_label),
                "watermark_unlocked": bool(watermark_unlocked),
                "created_at": _now_iso(),
                "last_used_at": None,
            }
            self._items.append(item)
            self._save()
            return self._public_item(item)

    def create_first_admin_with_value(
        self, *, name: str = "", key: str = ""
    ) -> dict[str, object]:
        with self._lock:
            self._reload_locked()
            if any(item.get("role") == "admin" for item in self._items):
                raise ValueError("初始化已完成")
            normalized_name = self._build_name_locked(name, role="admin")
            key_hash = self._build_key_hash_locked(key)
            item = {
                "id": uuid.uuid4().hex[:12],
                "name": normalized_name,
                "role": "admin",
                "key_hash": key_hash,
                "enabled": True,
                "watermark_label": "",
                "watermark_unlocked": False,
                "created_at": _now_iso(),
                "last_used_at": None,
            }
            self._items.append(item)
            self._save()
            return self._public_item(item)

    def delete_first_admin_if_key_matches(self, key_id: str, raw_key: str) -> bool:
        normalized_id = self._clean(key_id)
        candidate = self._clean(raw_key)
        if not normalized_id or not candidate:
            return False
        candidate_hash = _hash_key(candidate)
        with self._lock:
            self._reload_locked()
            for index, item in enumerate(self._items):
                if item.get("id") != normalized_id or item.get("role") != "admin":
                    continue
                if not hmac.compare_digest(
                    self._clean(item.get("key_hash")), candidate_hash
                ):
                    return False
                remaining_items = self._items[:index] + self._items[index + 1 :]
                if any(
                    next_item.get("role") == "admin" for next_item in remaining_items
                ):
                    return False
                self._items = remaining_items
                self._save()
                return True
        return False

    def update_key(
        self,
        key_id: str,
        updates: dict[str, object],
        *,
        role: AuthRole | None = None,
    ) -> dict[str, object] | None:
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return None
        with self._lock:
            self._reload_locked()
            for index, item in enumerate(self._items):
                if item.get("id") != normalized_id:
                    continue
                if role is not None and item.get("role") != role:
                    return None
                next_item = dict(item)
                next_role = "admin" if str(next_item.get("role") or "").strip().lower() == "admin" else "user"
                if "name" in updates and updates.get("name") is not None:
                    next_item["name"] = self._build_name_locked(
                        str(updates.get("name") or ""),
                        role=next_role,
                        exclude_id=normalized_id,
                    )
                if "enabled" in updates and updates.get("enabled") is not None:
                    next_item["enabled"] = bool(updates.get("enabled"))
                if "watermark_label" in updates and updates.get("watermark_label") is not None:
                    next_item["watermark_label"] = self._clean(updates.get("watermark_label"))[:64]
                if "watermark_unlocked" in updates and updates.get("watermark_unlocked") is not None:
                    next_item["watermark_unlocked"] = bool(updates.get("watermark_unlocked"))
                if "model_providers" in updates and updates.get("model_providers") is not None:
                    next_item["model_providers"] = self._normalize_model_providers(
                        updates.get("model_providers"),
                        existing=next_item.get("model_providers"),
                    )
                if "model_provider" in updates and updates.get("model_provider") is not None:
                    providers = self._normalize_model_providers(next_item.get("model_providers"))
                    selected_provider = dict(self._selected_model_provider(providers))
                    if not selected_provider:
                        selected_provider = {
                            "id": "default",
                            "type": "newapi",
                            "base_url": "",
                            "api_key": "",
                            "selected": True,
                        }
                    selected_provider["type"] = self._clean(updates.get("model_provider"))[:32] or "newapi"
                    next_item["model_providers"] = [
                        selected_provider if provider.get("id") == selected_provider.get("id") else {**provider, "selected": False}
                        for provider in providers
                    ] or [selected_provider]
                if "model_base_url" in updates and updates.get("model_base_url") is not None:
                    providers = self._normalize_model_providers(next_item.get("model_providers"))
                    selected_provider = dict(self._selected_model_provider(providers))
                    if not selected_provider:
                        selected_provider = {
                            "id": "default",
                            "type": self._clean(next_item.get("model_provider")) or "newapi",
                            "base_url": "",
                            "api_key": "",
                            "selected": True,
                        }
                    selected_provider["base_url"] = self._clean(updates.get("model_base_url")).rstrip("/")[:512]
                    next_item["model_providers"] = [
                        selected_provider if provider.get("id") == selected_provider.get("id") else {**provider, "selected": False}
                        for provider in providers
                    ] or [selected_provider]
                if "model_api_key" in updates and updates.get("model_api_key") is not None:
                    providers = self._normalize_model_providers(next_item.get("model_providers"))
                    selected_provider = dict(self._selected_model_provider(providers))
                    if not selected_provider:
                        selected_provider = {
                            "id": "default",
                            "type": self._clean(next_item.get("model_provider")) or "newapi",
                            "base_url": self._clean(next_item.get("model_base_url")).rstrip("/"),
                            "api_key": "",
                            "selected": True,
                        }
                    selected_provider["api_key"] = self._clean(updates.get("model_api_key"))
                    next_item["model_providers"] = [
                        selected_provider if provider.get("id") == selected_provider.get("id") else {**provider, "selected": False}
                        for provider in providers
                    ] or [selected_provider]
                if "preferences" in updates and isinstance(updates.get("preferences"), dict):
                    next_item["preferences"] = dict(updates["preferences"])
                if "key" in updates and updates.get("key") is not None:
                    next_item["key_hash"] = self._build_key_hash_locked(str(updates.get("key") or ""), exclude_id=normalized_id)
                next_item = self._sync_legacy_model_provider_fields(next_item)
                self._items[index] = next_item
                self._save()
                return self._public_item(next_item)
        return None

    def delete_key(self, key_id: str, *, role: AuthRole | None = None) -> bool:
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return False
        with self._lock:
            self._reload_locked()
            before = len(self._items)
            self._items = [
                item
                for item in self._items
                if not (item.get("id") == normalized_id and (role is None or item.get("role") == role))
            ]
            if len(self._items) == before:
                return False
            self._save()
            return True

    # ------------------------------------------------------------------
    # OIDC user management
    # ------------------------------------------------------------------

    def find_by_oidc_binding(
        self, auth_provider: str, auth_subject: str
    ) -> dict[str, object] | None:
        """Find a user by their OIDC provider and subject binding."""
        with self._lock:
            self._reload_locked()
            for item in self._items:
                if (
                    self._clean(item.get("auth_provider")) == auth_provider
                    and self._clean(item.get("auth_subject")) == auth_subject
                ):
                    return self._public_item(item)
        return None

    def find_by_email(self, email: str) -> dict[str, object] | None:
        """Find a user by email (case-insensitive)."""
        candidate = email.strip().lower()
        if not candidate:
            return None
        with self._lock:
            self._reload_locked()
            for item in self._items:
                item_email = self._clean(item.get("email") or "").lower()
                if item_email == candidate:
                    return self._public_item(item)
        return None

    def find_or_create_oidc_user(
        self,
        *,
        auth_provider: str,
        auth_subject: str,
        email: str = "",
        name: str = "",
    ) -> dict[str, object]:
        """Find existing OIDC-bound user or create a new one.

        Returns the public user item. Raises ValueError on conflicts.
        """
        normalized_provider = self._clean(auth_provider)
        normalized_subject = self._clean(auth_subject)
        if not normalized_provider or not normalized_subject:
            raise ValueError("OIDC 身份信息不完整")

        with self._lock:
            self._reload_locked()

            # 1. Try to find existing user by OIDC binding
            for item in self._items:
                if (
                    self._clean(item.get("auth_provider")) == normalized_provider
                    and self._clean(item.get("auth_subject")) == normalized_subject
                ):
                    if not bool(item.get("enabled", True)):
                        raise ValueError("此账号已被禁用，请联系管理员")
                    # Update name/email if changed
                    updated = False
                    next_item = dict(item)
                    normalized_email = email.strip().lower() if email else ""
                    normalized_name = name.strip() if name else ""
                    if normalized_email and self._clean(item.get("email") or "").lower() != normalized_email:
                        next_item["email"] = normalized_email
                        updated = True
                    if normalized_name and self._clean(item.get("name") or "") != normalized_name:
                        # Only update if the current name looks auto-generated
                        current_name = self._clean(item.get("name") or "")
                        if not current_name or current_name == self._default_name("user"):
                            next_item["name"] = normalized_name
                            updated = True
                    if updated:
                        for idx in range(len(self._items)):
                            if self._items[idx].get("id") == item.get("id"):
                                self._items[idx] = next_item
                                self._save()
                                break
                    return self._public_item(next_item)

            # 2. Check for email conflict: same email, different sub
            normalized_email = email.strip().lower() if email else ""
            if normalized_email:
                for item in self._items:
                    item_email = self._clean(item.get("email") or "").lower()
                    if item_email == normalized_email:
                        item_provider = self._clean(item.get("auth_provider") or "")
                        item_subject = self._clean(item.get("auth_subject") or "")
                        if item_provider != normalized_provider or item_subject != normalized_subject:
                            raise ValueError(
                                "该邮箱已被其他账号绑定，无法通过 OIDC 登录。请联系管理员处理账号合并。"
                            )

            # 3. Create new OIDC user
            normalized_name = name.strip() if name else (email.split("@")[0] if email else "")
            if not normalized_name:
                normalized_name = self._build_default_name_locked("user")
            else:
                normalized_name = self._build_name_locked(normalized_name, role="user")

            item: dict[str, object] = {
                "id": uuid.uuid4().hex[:12],
                "name": normalized_name,
                "role": "user",
                "key_hash": "",
                "enabled": True,
                "watermark_label": "",
                "watermark_unlocked": False,
                "model_provider": "",
                "model_base_url": "",
                "model_api_key": "",
                "preferences": {},
                "auth_provider": normalized_provider,
                "auth_subject": normalized_subject,
                "created_at": _now_iso(),
                "last_used_at": None,
            }
            if normalized_email:
                item["email"] = normalized_email

            self._items.append(item)
            self._save()

            return self._public_item(item)

    def apply_newapi_default_provider(
        self,
        key_id: str,
        *,
        base_url: str,
        api_key: str,
    ) -> dict[str, object] | None:
        normalized_id = self._clean(key_id)
        normalized_base_url = self._clean(base_url).rstrip("/")
        normalized_api_key = self._clean(api_key)
        if not normalized_id:
            return None
        if not normalized_base_url or not normalized_api_key:
            raise ValueError("NewAPI 默认供应商配置不完整")
        provider = {
            "id": "newapi-default",
            "type": "newapi",
            "base_url": normalized_base_url[:512],
            "api_key": normalized_api_key,
            "selected": True,
        }
        with self._lock:
            self._reload_locked()
            for index, item in enumerate(self._items):
                if item.get("id") != normalized_id:
                    continue
                providers = self._normalize_model_providers(item.get("model_providers"))
                next_providers = [
                    {**existing, "selected": False}
                    for existing in providers
                    if self._clean(existing.get("id")) != "newapi-default"
                ]
                next_providers.append(provider)
                next_item = dict(item)
                next_item["model_providers"] = next_providers
                next_item = self._sync_legacy_model_provider_fields(next_item)
                self._items[index] = next_item
                self._save()
                return self._public_item(next_item)
        return None

    def authenticate(self, raw_key: str) -> dict[str, object] | None:
        candidate = self._clean(raw_key)
        if not candidate:
            return None
        candidate_hash = _hash_key(candidate)
        with self._lock:
            for index, item in enumerate(self._items):
                if not bool(item.get("enabled", True)):
                    continue
                stored_hash = self._clean(item.get("key_hash"))
                if not stored_hash or not hmac.compare_digest(stored_hash, candidate_hash):
                    continue
                next_item = dict(item)
                now = datetime.now(timezone.utc)
                next_item["last_used_at"] = now.isoformat()
                self._items[index] = next_item
                item_id = self._clean(next_item.get("id"))
                last_flush_at = self._last_used_flush_at.get(item_id)
                if last_flush_at is None or (now - last_flush_at).total_seconds() >= 60:
                    try:
                        self._save()
                        self._last_used_flush_at[item_id] = now
                    except Exception:
                        pass
                public = self._public_item(next_item)
                public["model_api_key"] = self._selected_model_provider(next_item.get("model_providers")).get("api_key") or next_item.get("model_api_key") or ""
                return public
        return None


auth_service = AuthService(config.get_storage_backend())
