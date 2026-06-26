from __future__ import annotations

import secrets
import time
from urllib.parse import quote, unquote, urlsplit

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from api.support import (
    require_admin,
    require_identity,
    resolve_image_base_url,
    resolve_identity_for_request,
)
from services.auth_service import auth_service
from services.config import config
from services.image_access_service import (
    IMAGE_ACCESS_TOKEN_PARAM,
    verify_image_access_token,
)
from services.image_service import (
    compress_images,
    delete_images,
    delete_to_target,
    download_images_zip,
    get_image_download_response,
    get_image_response,
    get_thumbnail_response,
    list_images,
    storage_stats,
)
from services.image_storage_service import ImageStorageError, image_storage_service
from services.image_tags_service import delete_tag, get_all_tags, set_tags
from services.log_service import log_service
from services import model_gateway_service
from services.web_session_service import WebSessionError, web_session_service


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


class ImageDeleteRequest(BaseModel):
    paths: list[str] = []
    start_date: str = ""
    end_date: str = ""
    all_matching: bool = False


class ImageDownloadRequest(BaseModel):
    paths: list[str]


class ImageDownloadTokenRequest(BaseModel):
    paths: list[str] = []


class ImageAccessLinkRequest(BaseModel):
    path: str = ""
    url: str = ""


class ImageTagsRequest(BaseModel):
    path: str
    tags: list[str]


class LogDeleteRequest(BaseModel):
    ids: list[str] = []


class PasswordLoginRequest(BaseModel):
    email: str = ""
    password: str = ""


class RegisterRequest(BaseModel):
    name: str = ""
    email: str = ""
    password: str = ""
    confirm_password: str = ""


class SetupRequest(BaseModel):
    admin_name: str = ""
    admin_key: str = ""
    public_app_url: str = ""
    api_public_url: str = ""
    session_secret: str = ""
    oidc: dict[str, object] = {}
    model_gateway: dict[str, object] = {}


class AdminKeyLoginRequest(BaseModel):
    key: str = ""


class UserProfileUpdateRequest(BaseModel):
    watermark_label: str | None = None
    model_provider: str | None = None
    model_base_url: str | None = None
    model_api_key: str | None = None
    model_providers: list[dict[str, object]] | None = None
    preferences: dict[str, object] | None = None


class UserKeyCreateRequest(BaseModel):
    name: str = ""
    key: str | None = None


class UserKeyUpdateRequest(BaseModel):
    enabled: bool | None = None
    name: str | None = None
    key: str | None = None
    watermark_unlocked: bool | None = None


def _auth_identity_response(
    identity: dict[str, object], access_token: str, app_version: str
) -> dict[str, object]:
    role = "admin" if identity.get("role") == "admin" else "user"
    subject_id = str(identity.get("id") or "").strip() or role
    name = str(identity.get("name") or "").strip() or (
        "管理员" if role == "admin" else "创作者"
    )
    watermark_label = str(identity.get("watermark_label") or "").strip()
    watermark_unlocked = role == "admin" or bool(
        identity.get("watermark_unlocked", False)
    )
    model_provider = str(identity.get("model_provider") or "").strip()
    model_base_url = str(identity.get("model_base_url") or "").strip().rstrip("/")
    model_api_key_configured = bool(identity.get("model_api_key_configured")) or bool(
        str(identity.get("model_api_key") or "").strip()
    )
    model_gateway_enabled = model_gateway_service.is_enabled(
        model_base_url, str(identity.get("model_api_key") or "")
    )
    model_providers = (
        identity.get("model_providers")
        if isinstance(identity.get("model_providers"), list)
        else []
    )
    preferences = (
        identity.get("preferences")
        if isinstance(identity.get("preferences"), dict)
        else {}
    )
    external_identity = {
        key: str(identity.get(key) or "").strip()
        for key in ("auth_provider", "auth_subject", "email")
        if str(identity.get(key) or "").strip()
    }
    return {
        "ok": True,
        "version": app_version,
        "role": role,
        "subject_id": subject_id,
        "name": name,
        "watermark_label": watermark_label,
        "watermark_unlocked": watermark_unlocked,
        "model_provider": model_provider,
        "model_base_url": model_base_url,
        "model_api_key_configured": model_api_key_configured,
        "model_gateway_enabled": model_gateway_enabled,
        "model_providers": model_providers,
        "preferences": preferences,
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": None,
        **external_identity,
        "user": {
            "id": subject_id,
            "name": name,
            "role": role,
            "watermark_label": watermark_label,
            "watermark_unlocked": watermark_unlocked,
            "model_provider": model_provider,
            "model_base_url": model_base_url,
            "model_api_key_configured": model_api_key_configured,
            "model_gateway_enabled": model_gateway_enabled,
            "model_providers": model_providers,
            "preferences": preferences,
            **external_identity,
        },
    }


def _auth_login_response(
    identity: dict[str, object], access_token: str, app_version: str
) -> JSONResponse:
    payload = _auth_identity_response(identity, access_token, app_version)
    try:
        _session_token, cookie = web_session_service.create_session(identity)
    except WebSessionError:
        return JSONResponse(content=payload)
    response = JSONResponse(content=payload)
    response.headers["Set-Cookie"] = cookie
    return response


def _test_login_token(email: str, password: str) -> str:
    enabled = (
        str(
            config.data.get("test_accounts_enabled", "false")
        )
        .strip()
        .lower()
    )
    if enabled in {"0", "false", "no", "off"}:
        return ""
    normalized_email = email.strip().lower()
    normalized_password = password.strip().lower()
    if normalized_email == "admin" and normalized_password == "admin":
        return "admin"
    if normalized_email == "user" and normalized_password == "user":
        return "user"
    return ""


def _named_key_identity(email: str, password: str) -> dict[str, object] | None:
    identity = auth_service.authenticate(password)
    if identity is None:
        return None
    expected_name = str(identity.get("name") or "").strip().lower()
    candidate_email = email.strip().lower()
    if expected_name and expected_name == candidate_email:
        return identity
    return None


_DOWNLOAD_TOKENS: dict[str, tuple[float, dict[str, object]]] = {}
_DOWNLOAD_TOKEN_TTL_SECONDS = 120
_AUTH_ATTEMPTS: dict[str, list[float]] = {}
_AUTH_ATTEMPT_WINDOW_SECONDS = 600
_AUTH_ATTEMPT_LIMIT = 8


def _rate_limit_key(request: Request, scope: str, subject: str = "") -> str:
    host = request.client.host if request.client else "unknown"
    return f"{scope}:{host}:{subject.strip().lower()}"


def _check_auth_rate_limit(request: Request, scope: str, subject: str = "") -> None:
    now = time.time()
    key = _rate_limit_key(request, scope, subject)
    cutoff = now - _AUTH_ATTEMPT_WINDOW_SECONDS
    attempts = [item for item in _AUTH_ATTEMPTS.get(key, []) if item >= cutoff]
    if len(attempts) >= _AUTH_ATTEMPT_LIMIT:
        raise HTTPException(
            status_code=429, detail={"error": "尝试次数过多，请稍后再试"}
        )
    attempts.append(now)
    _AUTH_ATTEMPTS[key] = attempts


def _create_download_token(identity: dict[str, object]) -> str:
    now = time.time()
    expired = [
        key for key, (expires_at, _) in _DOWNLOAD_TOKENS.items() if expires_at < now
    ]
    for key in expired:
        _DOWNLOAD_TOKENS.pop(key, None)
    token = secrets.token_urlsafe(24)
    _DOWNLOAD_TOKENS[token] = (now + _DOWNLOAD_TOKEN_TTL_SECONDS, identity)
    return token


def _require_download_admin(
    request: Request,
    authorization: str | None,
    download_token: str = "",
) -> dict[str, object]:
    token = download_token.strip()
    if token:
        item = _DOWNLOAD_TOKENS.get(token)
        if item is None or item[0] < time.time():
            _DOWNLOAD_TOKENS.pop(token, None)
            raise HTTPException(
                status_code=401, detail={"error": "下载链接已失效，请重新点击下载"}
            )
        identity = item[1]
    else:
        identity = resolve_identity_for_request(request, authorization)
    if identity.get("role") != "admin":
        raise HTTPException(
            status_code=403, detail={"error": "需要管理员权限才能执行这个操作"}
        )
    return identity


def _extract_image_access_path(body: ImageAccessLinkRequest) -> str:
    raw = str(body.path or body.url or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail={"error": "path is required"})
    without_query = raw.split("?", 1)[0]
    parsed = urlsplit(raw)
    path = parsed.path if parsed.scheme or parsed.netloc else without_query
    if "/images/" in path:
        path = path.split("/images/", 1)[1]
    return unquote(path).strip().lstrip("/")


def _registration_enabled() -> bool:
    enabled = (
        str(
            config.data.get("registration_enabled", "false")
        )
        .strip()
        .lower()
    )
    return enabled not in {"0", "false", "no", "off"}


def _local_password_login_enabled() -> bool:
    enabled = (
        str(
            config.data.get("local_password_login_enabled", "false")
        )
        .strip()
        .lower()
    )
    return enabled in {"1", "true", "yes", "on"}


def _admin_exists() -> bool:
    return bool(auth_service.list_keys("admin"))


def _setup_status_payload() -> dict[str, object]:
    setup_required = not _admin_exists()
    payload: dict[str, object] = {
        "ok": True,
        "setup_required": setup_required,
    }
    if setup_required:
        payload["storage"] = _public_setup_storage_info()
    return payload


def _public_setup_storage_info() -> dict[str, object]:
    info = config.get_storage_backend().get_backend_info()
    return {
        "type": str(info.get("type") or "unknown"),
        "description": str(info.get("description") or ""),
        "status": "configured",
    }


def _normalize_setup_url(value: object, label: str, *, required: bool = False) -> str:
    normalized = str(value or "").strip().rstrip("/")
    if not normalized:
        if required:
            raise ValueError(f"{label} 必须填写")
        return ""
    if len(normalized) > 512:
        raise ValueError(f"{label} 不能超过 512 个字符")
    if not normalized.startswith(("http://", "https://")):
        raise ValueError(f"{label} 必须以 http:// 或 https:// 开头")
    return normalized


def _normalize_setup_config(body: SetupRequest) -> dict[str, object]:
    public_app_url = _normalize_setup_url(body.public_app_url, "公开应用地址")
    api_public_url = _normalize_setup_url(body.api_public_url, "公开 API 地址")
    session_secret = body.session_secret.strip()
    if len(session_secret) < 32:
        raise ValueError("Session Secret 至少需要 32 个字符")
    model_gateway = dict(body.model_gateway) if isinstance(body.model_gateway, dict) else {}
    for key, label in (
        ("gateway_api_base_url", "模型网关 API 地址"),
        ("gateway_management_url", "模型网关管理地址"),
        ("provision_url", "模型网关开通地址"),
    ):
        if key in model_gateway:
            model_gateway[key] = _normalize_setup_url(model_gateway.get(key), label)
    return {
        "public_app_url": public_app_url,
        "api_public_url": api_public_url,
        "session_secret": session_secret,
        "oidc": body.oidc,
        "model_gateway": model_gateway,
    }


def _normalize_register_name(body: RegisterRequest) -> str:
    name = (body.name or body.email or "").strip()
    if len(name) < 2:
        raise HTTPException(
            status_code=400, detail={"error": "账号名称至少需要 2 个字符"}
        )
    if len(name) > 64:
        raise HTTPException(
            status_code=400, detail={"error": "账号名称不能超过 64 个字符"}
        )
    if name.lower() in {"admin", "administrator", "root"}:
        raise HTTPException(
            status_code=400, detail={"error": "这个账号名称不可用于注册"}
        )
    return name


def _normalize_register_password(body: RegisterRequest) -> str:
    password = (body.password or "").strip()
    confirm_password = (body.confirm_password or "").strip()
    if len(password) < 6:
        raise HTTPException(status_code=400, detail={"error": "密码至少需要 6 个字符"})
    if len(password) > 128:
        raise HTTPException(
            status_code=400, detail={"error": "密码不能超过 128 个字符"}
        )
    if confirm_password and password != confirm_password:
        raise HTTPException(status_code=400, detail={"error": "两次输入的密码不一致"})
    return password


def _normalize_user_preferences(
    raw_preferences: dict[str, object],
) -> dict[str, object]:
    allowed_string_values = {
        "theme": {"system", "light", "dark"},
        "language": {"system", "zh-CN", "en-US"},
        "image_ratio": {"auto", "1:1", "4:3", "3:4", "16:9", "9:16"},
        "image_tier": {"1k", "2k", "4k"},
        "image_quality": {"auto", "low", "medium", "high"},
    }
    preferences: dict[str, object] = {}
    for key, allowed_values in allowed_string_values.items():
        if key not in raw_preferences:
            continue
        value = str(raw_preferences.get(key) or "").strip()
        if value in allowed_values:
            preferences[key] = value

    image_model = str(raw_preferences.get("image_model") or "").strip()
    if image_model and len(image_model) <= 128:
        preferences["image_model"] = image_model

    sidebar_collapsed = raw_preferences.get("sidebar_collapsed")
    if isinstance(sidebar_collapsed, bool):
        preferences["sidebar_collapsed"] = sidebar_collapsed

    try:
        sidebar_width = int(raw_preferences.get("sidebar_width"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        sidebar_width = 0
    if 220 <= sidebar_width <= 420:
        preferences["sidebar_width"] = sidebar_width

    return preferences


def create_router(app_version: str) -> APIRouter:
    router = APIRouter()

    @router.post("/auth/login")
    async def login(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        token = str(authorization or "").partition(" ")[2].strip()
        return _auth_login_response(identity, token, app_version)

    @router.post("/api/auth/login")
    async def password_login(request: Request, body: PasswordLoginRequest):
        if not _local_password_login_enabled():
            raise HTTPException(status_code=403, detail={"error": "请使用统一登录入口"})

        email = body.email.strip()
        password = body.password.strip()
        _check_auth_rate_limit(request, "password_login", email)
        if not email or not password:
            raise HTTPException(status_code=400, detail={"error": "请输入账号和密码"})

        named_key_identity = _named_key_identity(email, password)
        if named_key_identity:
            return _auth_login_response(named_key_identity, password, app_version)

        test_login_token = _test_login_token(email, password)
        if test_login_token:
            try:
                identity = require_identity(f"Bearer {test_login_token}")
                return _auth_login_response(identity, test_login_token, app_version)
            except HTTPException:
                pass
        raise HTTPException(status_code=401, detail={"error": "账号或密码不正确"})

    @router.get("/api/setup/status")
    async def get_setup_status():
        return _setup_status_payload()

    @router.post("/api/setup")
    async def complete_setup(body: SetupRequest):
        if _admin_exists():
            raise HTTPException(status_code=403, detail={"error": "初始化已完成"})
        admin_key = body.admin_key.strip()
        if len(admin_key) < 8:
            raise HTTPException(
                status_code=400, detail={"error": "管理员密钥至少需要 8 个字符"}
            )
        try:
            next_config = _normalize_setup_config(body)
            admin = await run_in_threadpool(
                auth_service.create_first_admin_with_value,
                name=body.admin_name.strip() or "管理员",
                key=admin_key,
            )
            try:
                config_response = config.update(next_config)
            except Exception:
                await run_in_threadpool(
                    auth_service.delete_first_admin_if_key_matches,
                    str(admin.get("id") or ""),
                    admin_key,
                )
                raise
        except ValueError as exc:
            if str(exc) == "初始化已完成":
                raise HTTPException(
                    status_code=403, detail={"error": "初始化已完成"}
                ) from exc
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {
            "ok": True,
            "setup_required": False,
            "admin": admin,
            "config": config_response,
        }

    @router.post("/api/auth/admin-key-login")
    async def admin_key_login(request: Request, body: AdminKeyLoginRequest):
        _check_auth_rate_limit(request, "admin_key_login", "admin")
        key = body.key.strip()
        if not key:
            raise HTTPException(status_code=400, detail={"error": "请输入管理员密钥"})
        identity = auth_service.authenticate(key)
        if identity is None or identity.get("role") != "admin":
            raise HTTPException(status_code=401, detail={"error": "管理员密钥无效"})
        return _auth_login_response(identity, key, app_version)

    @router.post("/api/auth/register")
    async def register_user(request: Request, body: RegisterRequest):
        raise HTTPException(status_code=403, detail={"error": "注册请使用统一登录入口"})

        _check_auth_rate_limit(request, "register", body.name)
        if not _registration_enabled():
            raise HTTPException(status_code=403, detail={"error": "注册功能暂未开放"})

        name = _normalize_register_name(body)
        password = _normalize_register_password(body)
        try:
            identity = await run_in_threadpool(
                auth_service.create_key_with_value,
                role="user",
                name=name,
                key=password,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return _auth_login_response(identity, password, app_version)

    @router.get("/api/auth/profile")
    async def get_auth_profile(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        return _auth_identity_response(identity, "", app_version)

    @router.patch("/api/auth/profile")
    async def update_auth_profile(
        body: UserProfileUpdateRequest, authorization: str | None = Header(default=None)
    ):
        identity = require_identity(authorization)
        role = "admin" if identity.get("role") == "admin" else "user"
        user_id = str(identity.get("id") or "").strip()
        if not user_id:
            raise HTTPException(
                status_code=401, detail={"error": "用户身份无效，请重新登录"}
            )
        updates: dict[str, object] = {}
        if body.watermark_label is not None and role == "user":
            watermark_label = body.watermark_label.strip()
            if len(watermark_label) > 64:
                raise HTTPException(
                    status_code=400, detail={"error": "水印标签不能超过 64 个字符"}
                )
            updates["watermark_label"] = watermark_label
        if body.model_provider is not None and role == "user":
            model_provider = body.model_provider.strip() or "newapi"
            if len(model_provider) > 32:
                raise HTTPException(
                    status_code=400, detail={"error": "供应商类型不能超过 32 个字符"}
                )
            updates["model_provider"] = model_provider
        if body.model_base_url is not None and role == "user":
            model_base_url = body.model_base_url.strip().rstrip("/")
            if model_base_url and not (
                model_base_url.startswith("http://")
                or model_base_url.startswith("https://")
            ):
                raise HTTPException(
                    status_code=400,
                    detail={"error": "Base URL 必须以 http:// 或 https:// 开头"},
                )
            if len(model_base_url) > 512:
                raise HTTPException(
                    status_code=400, detail={"error": "Base URL 不能超过 512 个字符"}
                )
            updates["model_base_url"] = model_base_url
        if body.model_api_key is not None and role == "user":
            updates["model_api_key"] = body.model_api_key.strip()
        if body.model_providers is not None and role == "user":
            model_providers: list[dict[str, object]] = []
            for raw_provider in body.model_providers:
                provider_type = (
                    str(
                        raw_provider.get("type")
                        or raw_provider.get("model_provider")
                        or "newapi"
                    ).strip()
                    or "newapi"
                )
                base_url = (
                    str(
                        raw_provider.get("base_url")
                        or raw_provider.get("model_base_url")
                        or ""
                    )
                    .strip()
                    .rstrip("/")
                )
                if len(provider_type) > 32:
                    raise HTTPException(
                        status_code=400,
                        detail={"error": "供应商类型不能超过 32 个字符"},
                    )
                if base_url and not (
                    base_url.startswith("http://") or base_url.startswith("https://")
                ):
                    raise HTTPException(
                        status_code=400,
                        detail={"error": "Base URL 必须以 http:// 或 https:// 开头"},
                    )
                if len(base_url) > 512:
                    raise HTTPException(
                        status_code=400,
                        detail={"error": "Base URL 不能超过 512 个字符"},
                    )
                if not base_url:
                    continue
                model_providers.append(
                    {
                        "id": str(raw_provider.get("id") or "").strip(),
                        "type": provider_type,
                        "base_url": base_url,
                        "api_key": str(raw_provider.get("api_key") or "").strip(),
                        "api_key_configured": bool(
                            raw_provider.get("api_key_configured")
                        ),
                        "selected": bool(raw_provider.get("selected")),
                    }
                )
            updates["model_providers"] = model_providers
        if body.preferences is not None:
            updates["preferences"] = _normalize_user_preferences(body.preferences)
        if not updates:
            raise HTTPException(status_code=400, detail={"error": "还没有检测到改动"})
        try:
            item = await run_in_threadpool(
                auth_service.update_key, user_id, updates, role=role
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "账号不存在"})
        response_identity = dict(item)
        response_identity.update(auth_service.get_model_gateway_config(user_id))
        return _auth_identity_response(response_identity, "", app_version)

    @router.get("/version")
    async def get_version():
        return {"version": app_version}

    @router.get("/api/settings")
    async def get_settings(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"config": config.get()}

    @router.post("/api/settings")
    async def save_settings(
        body: SettingsUpdateRequest, authorization: str | None = Header(default=None)
    ):
        require_admin(authorization)
        try:
            return {"config": config.update(body.model_dump(mode="python"))}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/auth/users")
    async def list_user_keys(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"items": await run_in_threadpool(auth_service.list_keys, "user")}

    @router.post("/api/auth/users")
    async def create_user_key(
        body: UserKeyCreateRequest, authorization: str | None = Header(default=None)
    ):
        require_admin(authorization)
        try:
            if body.key is not None and body.key.strip():
                item = await run_in_threadpool(
                    auth_service.create_key_with_value,
                    role="user",
                    name=body.name,
                    key=body.key,
                )
                raw_key = body.key.strip()
            else:
                item, raw_key = await run_in_threadpool(
                    auth_service.create_key, role="user", name=body.name
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {
            "item": item,
            "key": raw_key,
            "items": await run_in_threadpool(auth_service.list_keys, "user"),
        }

    @router.post("/api/auth/users/{key_id}")
    async def update_user_key(
        key_id: str,
        body: UserKeyUpdateRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        updates = body.model_dump(mode="python", exclude_unset=True)
        try:
            item = await run_in_threadpool(
                auth_service.update_key, key_id, updates, role="user"
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "账号不存在"})
        return {
            "item": item,
            "items": await run_in_threadpool(auth_service.list_keys, "user"),
        }

    @router.delete("/api/auth/users/{key_id}")
    async def delete_user_key(
        key_id: str, authorization: str | None = Header(default=None)
    ):
        require_admin(authorization)
        removed = await run_in_threadpool(auth_service.delete_key, key_id, role="user")
        if not removed:
            raise HTTPException(status_code=404, detail={"error": "账号不存在"})
        return {"items": await run_in_threadpool(auth_service.list_keys, "user")}

    @router.get("/api/images")
    async def get_images(
        request: Request,
        start_date: str = "",
        end_date: str = "",
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        include_all = identity.get("role") == "admin"
        return list_images(
            resolve_image_base_url(request),
            start_date=start_date.strip(),
            end_date=end_date.strip(),
            owner_id=str(identity.get("id") or ""),
            include_all=include_all,
        )

    @router.post("/api/images/access-link")
    async def create_image_access_link(
        body: ImageAccessLinkRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        image_path = _extract_image_access_path(body)
        include_all = identity.get("role") == "admin"
        user_id = str(identity.get("id") or "")
        image_items = image_storage_service.list_items(
            resolve_image_base_url(request), include_all=True
        )
        for item in image_items:
            if str(item.get("path") or item.get("rel") or "") == image_path:
                owner_id = str(item.get("owner_id") or "").strip()
                if owner_id and not include_all and owner_id != user_id:
                    break
                return {"url": item.get("url"), "path": image_path}
        raise HTTPException(status_code=404, detail={"error": "图片不存在或无权访问"})

    @router.get("/images/{image_path:path}", include_in_schema=False)
    async def get_image(
        request: Request,
        image_path: str,
        image_token: str = Query(default="", alias=IMAGE_ACCESS_TOKEN_PARAM),
        authorization: str | None = Header(default=None),
    ):
        if image_token:
            verify_image_access_token(image_path, image_token)
        else:
            resolve_identity_for_request(request, authorization)
        return get_image_response(image_path)

    @router.get("/image-thumbnails/{image_path:path}", include_in_schema=False)
    async def get_image_thumbnail(
        request: Request,
        image_path: str,
        image_token: str = Query(default="", alias=IMAGE_ACCESS_TOKEN_PARAM),
        authorization: str | None = Header(default=None),
    ):
        if image_token:
            verify_image_access_token(image_path, image_token)
        else:
            resolve_identity_for_request(request, authorization)
        return get_thumbnail_response(image_path)

    @router.post("/api/images/delete")
    async def delete_images_endpoint(
        body: ImageDeleteRequest, authorization: str | None = Header(default=None)
    ):
        require_admin(authorization)
        return delete_images(
            body.paths,
            start_date=body.start_date.strip(),
            end_date=body.end_date.strip(),
            all_matching=body.all_matching,
        )

    @router.post("/api/images/download")
    async def download_images_endpoint(
        body: ImageDownloadRequest, authorization: str | None = Header(default=None)
    ):
        require_admin(authorization)
        buf = download_images_zip(body.paths)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="images.zip"'},
        )

    @router.post("/api/images/download-token")
    async def create_image_download_token(
        body: ImageDownloadTokenRequest,
        authorization: str | None = Header(default=None),
    ):
        identity = require_admin(authorization)
        if not body.paths:
            raise HTTPException(status_code=400, detail={"error": "paths is required"})
        return {
            "token": _create_download_token(identity),
            "expires_in": _DOWNLOAD_TOKEN_TTL_SECONDS,
        }

    @router.get("/api/images/download")
    async def download_images_link_endpoint(
        request: Request,
        path: list[str] = Query(default=[]),
        paths: list[str] = Query(default=[]),
        download_token: str = Query(default=""),
        authorization: str | None = Header(default=None),
    ):
        _require_download_admin(request, authorization, download_token)
        selected_paths = path or paths
        buf = download_images_zip(selected_paths)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="images.zip"'},
        )

    @router.get("/api/images/download/{image_path:path}")
    async def download_single_image_endpoint(
        request: Request,
        image_path: str,
        download_token: str = Query(default=""),
        authorization: str | None = Header(default=None),
    ):
        _require_download_admin(request, authorization, download_token)
        return get_image_download_response(image_path)

    @router.get("/api/logs")
    async def get_logs(
        type: str = "",
        start_date: str = "",
        end_date: str = "",
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        return {
            "items": log_service.list(
                type=type.strip(),
                start_date=start_date.strip(),
                end_date=end_date.strip(),
            )
        }

    @router.post("/api/logs/delete")
    async def delete_logs(
        body: LogDeleteRequest, authorization: str | None = Header(default=None)
    ):
        require_admin(authorization)
        return log_service.delete(body.ids)

    @router.get("/api/storage/info")
    async def get_storage_info(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        storage = config.get_storage_backend()
        return {
            "backend": storage.get_backend_info(),
            "health": storage.health_check(),
        }

    @router.post("/api/image-storage/test")
    async def test_image_storage_endpoint(
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        return {"result": await run_in_threadpool(image_storage_service.test_webdav)}

    @router.post("/api/image-storage/sync")
    async def sync_image_storage_endpoint(
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        try:
            return {"result": await run_in_threadpool(image_storage_service.sync_all)}
        except ImageStorageError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/images/tags")
    async def list_image_tags(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"tags": get_all_tags()}

    @router.post("/api/images/tags")
    async def update_image_tags(
        body: ImageTagsRequest, authorization: str | None = Header(default=None)
    ):
        require_admin(authorization)
        rel = body.path.strip().lstrip("/")
        if not rel:
            raise HTTPException(status_code=400, detail={"error": "path is required"})
        tags = set_tags(rel, body.tags)
        return {"ok": True, "tags": tags}

    @router.delete("/api/images/tags/{tag}")
    async def delete_image_tag(
        tag: str, authorization: str | None = Header(default=None)
    ):
        require_admin(authorization)
        count = delete_tag(tag)
        return {"ok": True, "removed_from": count}

    @router.get("/api/images/storage")
    async def get_image_storage(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return storage_stats()

    @router.post("/api/images/storage/compress")
    async def compress_all_images(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return await run_in_threadpool(compress_images)

    @router.post("/api/images/storage/cleanup-to-target")
    async def cleanup_to_target(
        target_free_mb: int = 500,
        dry_run: bool = False,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        return await run_in_threadpool(delete_to_target, target_free_mb, dry_run)

    @router.get("/health", response_model=None)
    async def health_dashboard(
        format: str = Query(default="html"),
        detailed: bool = Query(default=False),
        authorization: str | None = Header(default=None),
    ):
        storage = config.get_storage_backend()
        storage_health = storage.health_check()
        healthy = bool(storage_health.get("ok", True))

        public_json = {
            "status": "ok" if healthy else "degraded",
            "healthy": healthy,
            "version": app_version,
        }
        if not detailed:
            if format == "json":
                return public_json
            status_text = "正常" if healthy else "异常"
            return HTMLResponse(
                '<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                "<title>Happy Token Health</title></head><body>"
                f"<h1>Happy Token Health</h1><p>{status_text}</p>"
                f"<p>v{app_version}</p></body></html>"
            )

        require_admin(authorization)
        stats_json = {
            **public_json,
            "storage": {
                "backend": storage.get_backend_info(),
                "health": storage_health,
            },
            "images": storage_stats(),
        }
        if format == "json":
            return stats_json
        return HTMLResponse(f"""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>服务健康监控 - Happy Token</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:system-ui,-apple-system,sans-serif;background:#0f1117;color:#e2e8f0;min-height:100vh}}
.header{{background:#1a1d27;border-bottom:1px solid #2a2d3a;padding:16px 24px;display:flex;justify-content:space-between;align-items:center}}
.header h1{{font-size:20px}}
.status-dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px}}
.status-ok{{background:#22c55e;box-shadow:0 0 8px #22c55e88}}
.status-degraded{{background:#f59e0b;box-shadow:0 0 8px #f59e0b88}}
.container{{max-width:960px;margin:0 auto;padding:24px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:24px}}
.card{{background:#1a1d27;border:1px solid #2a2d3a;border-radius:10px;padding:16px}}
.card .value{{font-size:28px;font-weight:700;margin:4px 0}}
.card .label{{font-size:13px;color:#94a3b8}}
.green{{color:#22c55e}}.yellow{{color:#f59e0b}}.red{{color:#ef4444}}.blue{{color:#6c63ff}}
table{{width:100%;border-collapse:collapse;background:#1a1d27;border:1px solid #2a2d3a;border-radius:10px;overflow:hidden}}
th{{background:#242836;font-weight:600;text-align:left;padding:10px 12px;font-size:12px;color:#94a3b8;text-transform:uppercase}}
td{{padding:8px 12px;border-top:1px solid #2a2d3a;font-size:14px}}tr:hover td{{background:rgba(108,99,255,.05)}}
.api-url{{font-family:monospace;font-size:12px;color:#6c63ff}}
.refresh{{font-size:12px;color:#64748b;text-align:center;margin-top:24px}}
</style>
<meta http-equiv="refresh" content="30">
</head>
<body>
<div class="header">
<h1><span class="status-dot {'status-ok' if healthy else 'status-degraded'}"></span>服务健康监控</h1>
<div style="font-size:13px;color:#94a3b8">v{app_version} · 30s 自动刷新</div>
</div>
<div class="container">
<div class="cards">
<div class="card"><div class="label">服务状态</div><div class="value {'green' if healthy else 'yellow'}">{'正常' if healthy else '异常'}</div></div>
<div class="card"><div class="label">存储后端</div><div class="value blue">{storage.get_backend_info().get('type', 'unknown')}</div></div>
<div class="card"><div class="label">图片数量</div><div class="value">{storage_stats().get('image_count', 0)}</div></div>
<div class="card"><div class="label">图片体积 MB</div><div class="value">{storage_stats().get('image_size_mb', 0)}</div></div>
</div>
<div class="refresh">JSON: <span class="api-url">/health?format=json</span></div>
</div></body></html>""")

    return router
