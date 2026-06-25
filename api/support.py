from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from services.auth_service import auth_service
from services.config import config

BASE_DIR = Path(__file__).resolve().parents[1]
WEB_DIST_DIR = BASE_DIR / "web_dist"
_CURRENT_REQUEST: ContextVar[Request | None] = ContextVar("happytoken_current_request", default=None)


def extract_bearer_token(authorization: str | None) -> str:
    scheme, _, value = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return ""
    return value.strip()


def set_current_request(request: Request):
    return _CURRENT_REQUEST.set(request)


def reset_current_request(token) -> None:
    _CURRENT_REQUEST.reset(token)


def current_request() -> Request | None:
    return _CURRENT_REQUEST.get()


def _origin_of(value: str) -> str:
    parsed = urlsplit(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".lower()


def _trusted_cookie_origins(request: Request) -> set[str]:
    request_origin = f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}".lower()
    origins = {request_origin}
    for value in [config.frontend_base_url, config.base_url, config.api_base_url, *config.cors_origins]:
        origin = _origin_of(str(value or ""))
        if origin:
            origins.add(origin)
    return origins


def _assert_cookie_origin_allowed(request: Request) -> None:
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = _origin_of(request.headers.get("origin", ""))
    if not origin:
        referer = _origin_of(request.headers.get("referer", ""))
        origin = referer
    if origin and origin not in _trusted_cookie_origins(request):
        raise HTTPException(status_code=403, detail={"error": "请求来源无效，请刷新页面后重试"})


def _resolve_cookie_identity(request: Request) -> dict[str, object] | None:
    """Try to resolve identity from a web session cookie."""
    from services.web_session_service import WebSessionError, web_session_service
    cookie_value = request.cookies.get(web_session_service.cookie_name, "")
    if not cookie_value:
        return None
    _assert_cookie_origin_allowed(request)
    try:
        identity = web_session_service.resolve_identity(cookie_value)
    except WebSessionError:
        return None

    # Verify the user still exists and is enabled
    user_id = str(identity.get("id") or "")
    user_item = auth_service.get_key(user_id)
    if user_item is None or not bool(user_item.get("enabled", True)):
        return None

    # Return fresh identity from storage
    fresh_identity = {
        "id": user_item.get("id", ""),
        "name": user_item.get("name", ""),
        "role": user_item.get("role", "user"),
        "watermark_label": user_item.get("watermark_label") or "",
        "watermark_unlocked": bool(user_item.get("watermark_unlocked", False)),
        "model_provider": user_item.get("model_provider") or "",
        "model_base_url": user_item.get("model_base_url") or "",
        "model_api_key": user_item.get("model_api_key") or "",
        "model_api_key_configured": bool(user_item.get("model_api_key_configured")),
        "model_providers": user_item.get("model_providers") if isinstance(user_item.get("model_providers"), list) else [],
        "preferences": user_item.get("preferences") if isinstance(user_item.get("preferences"), dict) else {},
    }
    for key in ("auth_provider", "auth_subject", "email"):
        value = str(user_item.get(key) or "").strip()
        if value:
            fresh_identity[key] = value
    fresh_identity.update(auth_service.get_model_gateway_config(user_id))
    return fresh_identity


def resolve_identity_for_request(
    request: Request,
    authorization: str | None = None,
) -> dict[str, object]:
    """Resolve identity from a signed web cookie or Bearer token."""
    token = extract_bearer_token(authorization)
    if token:
        identity = auth_service.authenticate(token)
        if identity is None:
            raise HTTPException(status_code=401, detail={"error": "密钥无效或已失效，请重新登录"})
        return identity

    cookie_identity = _resolve_cookie_identity(request)
    if cookie_identity is not None:
        return cookie_identity

    identity = auth_service.authenticate(token)
    if identity is None:
        raise HTTPException(status_code=401, detail={"error": "密钥无效或已失效，请重新登录"})
    return identity


def require_identity(authorization: str | None, request: Request | None = None) -> dict[str, object]:
    active_request = request or current_request()
    if active_request is not None:
        return resolve_identity_for_request(active_request, authorization)
    token = extract_bearer_token(authorization)
    identity = auth_service.authenticate(token)
    if identity is None:
        raise HTTPException(status_code=401, detail={"error": "密钥无效或已失效，请重新登录"})
    return identity


def require_auth_key(authorization: str | None) -> None:
    require_identity(authorization)


def require_admin(authorization: str | None, request: Request | None = None) -> dict[str, object]:
    identity = require_identity(authorization, request)
    if identity.get("role") != "admin":
        raise HTTPException(status_code=403, detail={"error": "需要管理员权限才能执行这个操作"})
    return identity


def resolve_image_base_url(request: Request) -> str:
    return config.base_url or f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"


def resolve_web_asset(requested_path: str) -> Path | None:
    if not WEB_DIST_DIR.exists():
        return None
    clean_path = requested_path.strip("/")
    base_dir = WEB_DIST_DIR.resolve()
    candidates = [base_dir / "index.html"] if not clean_path else [
        base_dir / Path(clean_path),
        base_dir / clean_path / "index.html",
        base_dir / f"{clean_path}.html",
    ]
    for candidate in candidates:
        try:
            candidate.resolve().relative_to(base_dir)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None
