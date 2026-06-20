from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone
from threading import Lock
from typing import Literal

from services.config import config
from services.log_service import LOG_TYPE_USER_QUOTA, log_service
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
        image_quota = raw.get("image_quota")
        if image_quota is not None:
            try:
                image_quota = max(0, int(image_quota))
            except (TypeError, ValueError):
                image_quota = 0
        watermark_label = self._clean(raw.get("watermark_label"))
        watermark_unlocked = bool(raw.get("watermark_unlocked", False))
        email = self._clean(raw.get("email")) or None
        item: dict[str, object] = {
            "id": item_id,
            "name": name,
            "role": role,
            "key_hash": key_hash,
            "enabled": bool(raw.get("enabled", True)),
            "image_quota": image_quota,
            "watermark_label": watermark_label,
            "watermark_unlocked": watermark_unlocked,
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
        public: dict[str, object] = {
            "id": item.get("id"),
            "name": item.get("name"),
            "role": item.get("role"),
            "enabled": bool(item.get("enabled", True)),
            "image_quota": item.get("image_quota"),
            "watermark_label": item.get("watermark_label") or "",
            "watermark_unlocked": bool(item.get("watermark_unlocked", False)),
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
        admin_key = self._clean(config.auth_key)
        if admin_key and hmac.compare_digest(candidate, admin_key):
            raise ValueError("这个密钥和管理员密钥冲突了，请换一个新的密钥")
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

    @staticmethod
    def _normalize_image_quota(image_quota: object) -> int | None:
        if image_quota is None:
            return None
        try:
            return max(0, int(image_quota))
        except (TypeError, ValueError) as exc:
            raise ValueError("图片额度必须是非负整数") from exc

    def create_key(
        self,
        *,
        role: AuthRole,
        name: str = "",
        image_quota: object = None,
        watermark_label: str = "",
        watermark_unlocked: bool = False,
    ) -> tuple[dict[str, object], str]:
        with self._lock:
            self._reload_locked()
            normalized_name = self._build_name_locked(name, role=role)
            normalized_quota = self._normalize_image_quota(image_quota)
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
                "image_quota": normalized_quota,
                "watermark_label": self._clean(watermark_label),
                "watermark_unlocked": bool(watermark_unlocked),
                "created_at": _now_iso(),
                "last_used_at": None,
            }
            self._items.append(item)
            self._save()
            if role == "user":
                log_service.add(
                    LOG_TYPE_USER_QUOTA,
                    "创建用户",
                    {
                        "action": "create",
                        "user_id": item["id"],
                        "user_name": item["name"],
                        "amount": normalized_quota or 0,
                        "before_quota": 0,
                        "after_quota": normalized_quota,
                        "enabled": True,
                    },
                )
            return self._public_item(item), raw_key

    def create_key_with_value(
        self,
        *,
        role: AuthRole,
        name: str = "",
        key: str = "",
        image_quota: object = None,
        watermark_label: str = "",
        watermark_unlocked: bool = False,
    ) -> dict[str, object]:
        with self._lock:
            self._reload_locked()
            normalized_name = self._build_name_locked(name, role=role)
            key_hash = self._build_key_hash_locked(key)
            normalized_quota = self._normalize_image_quota(image_quota)
            item = {
                "id": uuid.uuid4().hex[:12],
                "name": normalized_name,
                "role": role,
                "key_hash": key_hash,
                "enabled": True,
                "image_quota": normalized_quota,
                "watermark_label": self._clean(watermark_label),
                "watermark_unlocked": bool(watermark_unlocked),
                "created_at": _now_iso(),
                "last_used_at": None,
            }
            self._items.append(item)
            self._save()
            if role == "user":
                log_service.add(
                    LOG_TYPE_USER_QUOTA,
                    "创建用户",
                    {
                        "action": "create",
                        "user_id": item["id"],
                        "user_name": item["name"],
                        "amount": normalized_quota or 0,
                        "before_quota": 0,
                        "after_quota": normalized_quota,
                        "enabled": True,
                    },
                )
            return self._public_item(item)

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
                if "image_quota" in updates:
                    quota = updates.get("image_quota")
                    if quota is None:
                        next_item["image_quota"] = None
                    else:
                        try:
                            next_item["image_quota"] = max(0, int(quota))
                        except (TypeError, ValueError) as exc:
                            raise ValueError("图片额度必须是非负整数") from exc
                if "watermark_label" in updates and updates.get("watermark_label") is not None:
                    next_item["watermark_label"] = self._clean(updates.get("watermark_label"))[:64]
                if "watermark_unlocked" in updates and updates.get("watermark_unlocked") is not None:
                    next_item["watermark_unlocked"] = bool(updates.get("watermark_unlocked"))
                if "key" in updates and updates.get("key") is not None:
                    next_item["key_hash"] = self._build_key_hash_locked(str(updates.get("key") or ""), exclude_id=normalized_id)
                self._items[index] = next_item
                self._save()
                old_quota_raw = item.get("image_quota")
                new_quota_raw = next_item.get("image_quota")
                old_quota = None if old_quota_raw is None else max(0, int(old_quota_raw))
                new_quota = None if new_quota_raw is None else max(0, int(new_quota_raw))
                if next_role == "user":
                    quota_changed = old_quota != new_quota
                    enabled_changed = bool(item.get("enabled", True)) != bool(next_item.get("enabled", True))
                    if quota_changed or enabled_changed or ("name" in updates):
                        delta = None
                        if old_quota is not None and new_quota is not None:
                            delta = new_quota - old_quota
                        action = "adjust"
                        if enabled_changed:
                            action = "enable" if bool(next_item.get("enabled", True)) else "disable"
                        elif isinstance(delta, int) and delta > 0:
                            action = "recharge"
                        log_service.add(
                            LOG_TYPE_USER_QUOTA,
                            "更新用户",
                            {
                                "action": action,
                                "user_id": next_item["id"],
                                "user_name": next_item["name"],
                                "before_quota": old_quota,
                                "after_quota": new_quota,
                                "amount": delta,
                                "enabled_before": bool(item.get("enabled", True)),
                                "enabled_after": bool(next_item.get("enabled", True)),
                            },
                        )
                return self._public_item(next_item)
        return None

    def reserve_image_quota(self, identity: dict[str, object], amount: int = 1) -> bool:
        if identity.get("role") == "admin":
            return False
        try:
            normalized_amount = max(1, int(amount))
        except (TypeError, ValueError):
            normalized_amount = 1
        key_id = self._clean(identity.get("id"))
        if not key_id:
            raise ValueError("用户身份无效")
        with self._lock:
            self._reload_locked()
            for index, item in enumerate(self._items):
                if item.get("id") != key_id:
                    continue
                quota = item.get("image_quota")
                if quota is None:
                    return False
                remaining = max(0, int(quota))
                if remaining < normalized_amount:
                    raise ValueError("用户图片额度不足")
                next_item = dict(item)
                next_item["image_quota"] = remaining - normalized_amount
                self._items[index] = next_item
                self._save()
                identity["image_quota"] = next_item["image_quota"]
                log_service.add(
                    LOG_TYPE_USER_QUOTA,
                    "消耗额度",
                    {
                        "action": "consume",
                        "user_id": next_item["id"],
                        "user_name": next_item["name"],
                        "amount": normalized_amount,
                        "before_quota": remaining,
                        "after_quota": next_item["image_quota"],
                    },
                )
                return True
        raise ValueError("用户身份无效")

    def refund_image_quota(self, identity: dict[str, object], amount: int = 1) -> None:
        if identity.get("role") == "admin":
            return
        try:
            normalized_amount = max(1, int(amount))
        except (TypeError, ValueError):
            normalized_amount = 1
        key_id = self._clean(identity.get("id"))
        if not key_id:
            return
        with self._lock:
            self._reload_locked()
            for index, item in enumerate(self._items):
                if item.get("id") != key_id:
                    continue
                quota = item.get("image_quota")
                if quota is None:
                    return
                next_item = dict(item)
                next_item["image_quota"] = max(0, int(quota)) + normalized_amount
                self._items[index] = next_item
                self._save()
                identity["image_quota"] = next_item["image_quota"]
                log_service.add(
                    LOG_TYPE_USER_QUOTA,
                    "返还额度",
                    {
                        "action": "refund",
                        "user_id": next_item["id"],
                        "user_name": next_item["name"],
                        "amount": normalized_amount,
                        "before_quota": max(0, int(quota)),
                        "after_quota": next_item["image_quota"],
                    },
                )
                return

    def delete_key(self, key_id: str, *, role: AuthRole | None = None) -> bool:
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return False
        with self._lock:
            self._reload_locked()
            removed_items = [
                item for item in self._items
                if item.get("id") == normalized_id and (role is None or item.get("role") == role)
            ]
            before = len(self._items)
            self._items = [
                item
                for item in self._items
                if not (item.get("id") == normalized_id and (role is None or item.get("role") == role))
            ]
            if len(self._items) == before:
                return False
            self._save()
            for item in removed_items:
                if item.get("role") == "user":
                    quota_raw = item.get("image_quota")
                    quota = None if quota_raw is None else max(0, int(quota_raw))
                    log_service.add(
                        LOG_TYPE_USER_QUOTA,
                        "删除用户",
                        {
                            "action": "delete",
                            "user_id": item.get("id"),
                            "user_name": item.get("name"),
                            "before_quota": quota,
                            "after_quota": None,
                            "amount": None,
                            "enabled_before": bool(item.get("enabled", True)),
                            "enabled_after": False,
                        },
                    )
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
        default_image_quota: int = 0,
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
                "image_quota": default_image_quota,
                "watermark_label": "",
                "watermark_unlocked": False,
                "auth_provider": normalized_provider,
                "auth_subject": normalized_subject,
                "created_at": _now_iso(),
                "last_used_at": None,
            }
            if normalized_email:
                item["email"] = normalized_email

            self._items.append(item)
            self._save()

            log_service.add(
                LOG_TYPE_USER_QUOTA,
                "OIDC 自动创建用户",
                {
                    "action": "oidc_create",
                    "user_id": item["id"],
                    "user_name": item["name"],
                    "amount": default_image_quota,
                    "before_quota": 0,
                    "after_quota": default_image_quota,
                    "enabled": True,
                    "auth_provider": normalized_provider,
                },
            )

            return self._public_item(item)

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
                return self._public_item(next_item)
        return None


auth_service = AuthService(config.get_storage_backend())
