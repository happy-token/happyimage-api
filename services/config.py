from __future__ import annotations

from dataclasses import dataclass
import json
import os
import sys
from pathlib import Path
import time

from services.storage.base import StorageBackend

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = BASE_DIR / "config.json"
VERSION_FILE = BASE_DIR / "VERSION"
DOTENV_FILE = BASE_DIR / ".env"

DEFAULT_IMAGE_STORAGE = {
    "enabled": False,
    "mode": "local",
    "webdav_url": "",
    "webdav_username": "",
    "webdav_password": "",
    "webdav_root_path": "happytoken/images",
    "public_base_url": "",
}


def _load_prefixed_dotenv() -> None:
    if not DOTENV_FILE.exists() or not DOTENV_FILE.is_file():
        return
    try:
        lines = DOTENV_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key.startswith(("HAPPYTOKEN_", "HAPPYIMAGE_")):
            continue
        if key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


_load_prefixed_dotenv()


def _normalize_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _normalize_positive_int(value: object, default: int, minimum: int = 0) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return max(minimum, normalized)


def _getenv(name: str) -> str:
    value = str(os.getenv(name) or "").strip()
    if value or not name.startswith("HAPPYTOKEN_"):
        return value
    legacy_name = "HAPPYIMAGE_" + name.removeprefix("HAPPYTOKEN_")
    return str(os.getenv(legacy_name) or "").strip()


def _normalize_image_storage_settings(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    mode = str(source.get("mode") or "local").strip().lower()
    if mode not in {"local", "webdav", "both"}:
        mode = "local"
    enabled = _normalize_bool(source.get("enabled"), False)
    if not enabled:
        mode = "local"
    root_path = str(source.get("webdav_root_path") or DEFAULT_IMAGE_STORAGE["webdav_root_path"]).strip().strip("/")
    return {
        "enabled": enabled,
        "mode": mode,
        "webdav_url": str(source.get("webdav_url") or "").strip().rstrip("/"),
        "webdav_username": str(source.get("webdav_username") or "").strip(),
        "webdav_password": str(source.get("webdav_password") or "").strip(),
        "webdav_root_path": root_path or str(DEFAULT_IMAGE_STORAGE["webdav_root_path"]),
        "public_base_url": str(source.get("public_base_url") or "").strip().rstrip("/"),
    }


def _normalize_oidc_settings(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    return {
        "enabled": _normalize_bool(
            _getenv("HAPPYTOKEN_OIDC_ENABLED") or source.get("enabled"), False
        ),
        "issuer": str(
            _getenv("HAPPYTOKEN_OIDC_ISSUER") or source.get("issuer") or ""
        ).strip().rstrip("/"),
        "client_id": str(
            _getenv("HAPPYTOKEN_OIDC_CLIENT_ID") or source.get("client_id") or ""
        ).strip(),
        "client_secret": str(
            _getenv("HAPPYTOKEN_OIDC_CLIENT_SECRET") or source.get("client_secret") or ""
        ).strip(),
        "scopes": str(
            _getenv("HAPPYTOKEN_OIDC_SCOPES") or source.get("scopes") or "openid profile email"
        ).strip(),
        "allowed_email_domains": str(
            _getenv("HAPPYTOKEN_OIDC_ALLOWED_EMAIL_DOMAINS")
            or source.get("allowed_email_domains")
            or ""
        ).strip(),
    }


def _redact_oidc_secret(oidc: dict[str, object]) -> dict[str, object]:
    redacted = dict(oidc)
    if str(redacted.get("client_secret") or "").strip():
        redacted["client_secret_configured"] = True
    else:
        redacted["client_secret_configured"] = False
    redacted.pop("client_secret", None)
    return redacted


def _validate_image_storage_settings(settings: dict[str, object]) -> None:
    if not _normalize_bool(settings.get("enabled"), False):
        return
    if not str(settings.get("webdav_url") or "").strip():
        raise ValueError("启用 WebDAV 图片存储后必须填写 WebDAV URL")
    if not str(settings.get("webdav_password") or "").strip():
        raise ValueError("启用 WebDAV 图片存储后必须填写 WebDAV 密码")


@dataclass(frozen=True)
class LoadedSettings:
    refresh_account_interval_minute: int


def _read_json_object(path: Path, *, name: str) -> dict[str, object]:
    if not path.exists():
        return {}
    if path.is_dir():
        print(
            f"Warning: {name} at '{path}' is a directory, ignoring it and falling back to other configuration sources.",
            file=sys.stderr,
        )
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_settings() -> LoadedSettings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_config = _read_json_object(CONFIG_FILE, name="config.json")

    try:
        refresh_interval = int(raw_config.get("refresh_account_interval_minute", 5))
    except (TypeError, ValueError):
        refresh_interval = 5

    return LoadedSettings(refresh_account_interval_minute=refresh_interval)


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.data = self._load()
        self._storage_backend: StorageBackend | None = None

    def _load(self) -> dict[str, object]:
        return _read_json_object(self.path, name="config.json")

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @property
    def accounts_file(self) -> Path:
        return DATA_DIR / "accounts.json"

    @property
    def refresh_account_interval_minute(self) -> int:
        try:
            return int(self.data.get("refresh_account_interval_minute", 5))
        except (TypeError, ValueError):
            return 5

    @property
    def image_retention_days(self) -> int:
        try:
            return max(1, int(self.data.get("image_retention_days", 30)))
        except (TypeError, ValueError):
            return 30

    @property
    def image_poll_timeout_secs(self) -> int:
        try:
            return max(1, int(self.data.get("image_poll_timeout_secs", 120)))
        except (TypeError, ValueError):
            return 120

    @property
    def image_poll_interval_secs(self) -> float:
        try:
            return max(0.5, float(self.data.get("image_poll_interval_secs", 10.0)))
        except (TypeError, ValueError):
            return 10.0

    @property
    def image_poll_initial_wait_secs(self) -> float:
        """Image generation upstream takes ~30s; polling immediately wastes requests
        and trips a transient 429. Default 10s gives the conversation document time
        to commit before the first poll."""
        try:
            return max(0.0, float(self.data.get("image_poll_initial_wait_secs", 10.0)))
        except (TypeError, ValueError):
            return 10.0

    @property
    def image_account_concurrency(self) -> int:
        try:
            return max(1, int(self.data.get("image_account_concurrency", 3)))
        except (TypeError, ValueError):
            return 3

    @property
    def image_parallel_generation(self) -> bool:
        value = self.data.get("image_parallel_generation", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def image_settle_enabled(self) -> bool:
        """图片二次确认机制：找到 file_ids 后等待一段时间再次确认。"""
        value = self.data.get("image_settle_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def image_check_before_hit_enabled(self) -> bool:
        """先check再hit：通过轮询确认 file_ids 存在后再返回，而非仅依赖 SSE 事件。"""
        value = self.data.get("image_check_before_hit_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def image_settle_secs(self) -> float:
        """二次确认等待时间（秒）。"""
        try:
            return max(0.5, float(self.data.get("image_settle_secs", 2.0)))
        except (TypeError, ValueError):
            return 2.0

    @property
    def auto_relogin_after_refresh(self) -> bool:
        value = self.data.get("auto_relogin_after_refresh", False)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def log_levels(self) -> list[str]:
        levels = self.data.get("log_levels")
        if not isinstance(levels, list):
            return []
        allowed = {"debug", "info", "warning", "error"}
        return [level for item in levels if (level := str(item or "").strip().lower()) in allowed]

    @property
    def sensitive_words(self) -> list[str]:
        words = self.data.get("sensitive_words")
        return [word for item in words if (word := str(item or "").strip())] if isinstance(words, list) else []

    @property
    def ai_review(self) -> dict[str, object]:
        value = self.data.get("ai_review")
        return value if isinstance(value, dict) else {}

    @property
    def global_system_prompt(self) -> str:
        return str(self.data.get("global_system_prompt") or "").strip()

    @property
    def images_dir(self) -> Path:
        path = DATA_DIR / "images"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def image_thumbnails_dir(self) -> Path:
        path = DATA_DIR / "image_thumbnails"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cleanup_old_images(self) -> int:
        cutoff = time.time() - self.image_retention_days * 86400
        removed = 0
        for path in self.images_dir.rglob("*"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        for path in sorted((p for p in self.images_dir.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            try:
                path.rmdir()
            except OSError:
                pass
        return removed

    @property
    def base_url(self) -> str:
        return str(
            _getenv("HAPPYTOKEN_BASE_URL")
            or self.data.get("base_url")
            or ""
        ).strip().rstrip("/")

    @property
    def frontend_base_url(self) -> str:
        return str(
            _getenv("HAPPYTOKEN_FRONTEND_BASE_URL")
            or self.data.get("frontend_base_url")
            or ""
        ).strip().rstrip("/")

    @property
    def api_base_url(self) -> str:
        return str(
            _getenv("HAPPYTOKEN_API_BASE_URL")
            or self.data.get("api_base_url")
            or self.base_url
            or ""
        ).strip().rstrip("/")

    @property
    def cors_origins(self) -> list[str]:
        env_value = _getenv("HAPPYTOKEN_CORS_ORIGINS")
        if env_value:
            return [origin.strip() for origin in env_value.split(",") if origin.strip()]
        frontend = self.frontend_base_url
        if frontend:
            return [frontend]
        config_origins = self.data.get("cors_origins")
        if isinstance(config_origins, list):
            return [str(origin).strip() for origin in config_origins if str(origin).strip()]
        return []

    @property
    def session_secret(self) -> str:
        return str(
            _getenv("HAPPYTOKEN_SESSION_SECRET")
            or self.data.get("session_secret")
            or ""
        ).strip()

    @property
    def session_cookie_name(self) -> str:
        value = str(
            _getenv("HAPPYTOKEN_SESSION_COOKIE_NAME")
            or self.data.get("session_cookie_name")
            or "happytoken_session"
        ).strip()
        return "happytoken_session" if value == "happyimage_session" else value

    @property
    def session_max_age_seconds(self) -> int:
        try:
            return max(60, int(
                _getenv("HAPPYTOKEN_SESSION_MAX_AGE_SECONDS")
                or self.data.get("session_max_age_seconds", 86400)
            ))
        except (TypeError, ValueError):
            return 86400

    @property
    def app_version(self) -> str:
        try:
            value = VERSION_FILE.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return "0.0.0"
        return value or "0.0.0"

    def get(self) -> dict[str, object]:
        data = dict(self.data)
        data["proxy"] = self.get_proxy_settings()
        data["image_retention_days"] = self.image_retention_days
        data["image_poll_timeout_secs"] = self.image_poll_timeout_secs
        data["image_poll_interval_secs"] = self.image_poll_interval_secs
        data["image_poll_initial_wait_secs"] = self.image_poll_initial_wait_secs
        data["image_parallel_generation"] = self.image_parallel_generation
        data["log_levels"] = self.log_levels
        data["sensitive_words"] = self.sensitive_words
        data["ai_review"] = self.ai_review
        data["global_system_prompt"] = self.global_system_prompt
        data["frontend_base_url"] = self.frontend_base_url
        data["api_base_url"] = self.api_base_url
        data["cors_origins"] = self.cors_origins
        data["session_cookie_name"] = self.session_cookie_name
        data["session_max_age_seconds"] = self.session_max_age_seconds
        data["session_secret_configured"] = bool(self.session_secret)
        data["oidc"] = _redact_oidc_secret(self.get_oidc_settings())
        data["image_storage"] = self.get_image_storage_settings()
        data.pop("auth-key", None)
        data.pop("session_secret", None)
        data.pop("model_gateway_api_key", None)
        data.pop("model_gateway_provider", None)
        data.pop("model_gateway_base_url", None)
        data.pop("model_gateway_api_key_configured", None)
        data.pop("refresh_account_interval_minute", None)
        data.pop("image_account_concurrency", None)
        data.pop("auto_remove_invalid_accounts", None)
        data.pop("auto_remove_rate_limited_accounts", None)
        data.pop("auto_relogin_after_refresh", None)
        data.pop("backup", None)
        data.pop("backup_state", None)
        data.pop("chat_completion_cache", None)
        return data

    def get_proxy_settings(self) -> str:
        return str(_getenv("HAPPYTOKEN_PROXY") or self.data.get("proxy") or "").strip()

    def update(self, data: dict[str, object]) -> dict[str, object]:
        next_data = dict(self.data)
        next_data.update(dict(data or {}))
        if "image_storage" in next_data:
            next_data["image_storage"] = _normalize_image_storage_settings(next_data.get("image_storage"))
            _validate_image_storage_settings(next_data["image_storage"])
        if "oidc" in next_data:
            incoming_oidc = next_data.get("oidc")
            if isinstance(incoming_oidc, dict):
                normalized = _normalize_oidc_settings(incoming_oidc)
                if not str(normalized.get("client_secret") or "").strip():
                    normalized["client_secret"] = self.get_oidc_settings().get("client_secret", "")
                next_data["oidc"] = normalized
        next_data.pop("backup_state", None)
        next_data.pop("session_secret_configured", None)
        next_data.pop("model_gateway_api_key_configured", None)
        next_data.pop("model_gateway_api_key", None)
        next_data.pop("model_gateway_provider", None)
        next_data.pop("model_gateway_base_url", None)
        next_data.pop("refresh_account_interval_minute", None)
        next_data.pop("image_account_concurrency", None)
        next_data.pop("auto_remove_invalid_accounts", None)
        next_data.pop("auto_remove_rate_limited_accounts", None)
        next_data.pop("auto_relogin_after_refresh", None)
        next_data.pop("backup", None)
        next_data.pop("chat_completion_cache", None)
        self.data = next_data
        self._save()
        return self.get()

    def get_image_storage_settings(self) -> dict[str, object]:
        return _normalize_image_storage_settings(self.data.get("image_storage"))

    def get_oidc_settings(self) -> dict[str, object]:
        return _normalize_oidc_settings(self.data.get("oidc"))

    def get_storage_backend(self) -> StorageBackend:
        """获取存储后端实例（单例）"""
        if self._storage_backend is None:
            from services.storage.factory import create_storage_backend
            self._storage_backend = create_storage_backend(DATA_DIR)
        return self._storage_backend

config = ConfigStore(CONFIG_FILE)
