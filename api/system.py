from __future__ import annotations

import os
import secrets
import time
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict

from api.support import require_admin, require_identity, resolve_image_base_url, resolve_identity_for_request
from services.auth_service import auth_service
from services.backup_service import BackupError, backup_service
from services.config import config
from services.image_access_service import IMAGE_ACCESS_TOKEN_PARAM, verify_image_access_token
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
from services.proxy_service import test_proxy
from services.web_session_service import WebSessionError, web_session_service


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


class ProxyTestRequest(BaseModel):
    url: str = ""


class ImageDeleteRequest(BaseModel):
    paths: list[str] = []
    start_date: str = ""
    end_date: str = ""
    all_matching: bool = False

class ImageDownloadRequest(BaseModel):
    paths: list[str]

class ImageDownloadTokenRequest(BaseModel):
    paths: list[str] = []

class ImageTagsRequest(BaseModel):
    path: str
    tags: list[str]

class LogDeleteRequest(BaseModel):
    ids: list[str] = []
class BackupDeleteRequest(BaseModel):
    key: str = ""


class PasswordLoginRequest(BaseModel):
    email: str = ""
    password: str = ""
    access_key: str = ""


class RegisterRequest(BaseModel):
    name: str = ""
    email: str = ""
    password: str = ""
    confirm_password: str = ""


def _auth_identity_response(identity: dict[str, object], access_token: str, app_version: str) -> dict[str, object]:
    role = "admin" if identity.get("role") == "admin" else "user"
    subject_id = str(identity.get("id") or "").strip() or role
    name = str(identity.get("name") or "").strip() or ("管理员" if role == "admin" else "创作者")
    image_quota = identity.get("image_quota") if role == "user" else None
    return {
        "ok": True,
        "version": app_version,
        "role": role,
        "subject_id": subject_id,
        "name": name,
        "image_quota": image_quota,
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": None,
        "user": {
            "id": subject_id,
            "name": name,
            "role": role,
            "image_quota": image_quota,
        },
    }


def _auth_login_response(identity: dict[str, object], access_token: str, app_version: str) -> JSONResponse:
    payload = _auth_identity_response(identity, access_token, app_version)
    try:
        _session_token, cookie = web_session_service.create_session(identity)
    except WebSessionError:
        return JSONResponse(content=payload)
    response = JSONResponse(content=payload)
    response.headers["Set-Cookie"] = cookie
    return response


def _configured_login_email() -> str:
    return str(
        os.getenv("HAPPYIMAGE_LOGIN_EMAIL")
        or os.getenv("HAPPYIMAGE_LOGIN_USERNAME")
        or "admin"
    ).strip()


def _configured_login_password() -> str:
    return str(os.getenv("HAPPYIMAGE_LOGIN_PASSWORD") or config.auth_key or "").strip()


def _test_login_token(email: str, password: str) -> str:
    enabled = str(
        os.getenv("HAPPYIMAGE_TEST_ACCOUNTS_ENABLED")
        or config.data.get("test_accounts_enabled", "false")
    ).strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return ""
    if email == "admin" and password == "admin":
        return "admin"
    if email == "user" and password == "user":
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
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip = forwarded or host
    return f"{scope}:{ip}:{subject.strip().lower()}"


def _check_auth_rate_limit(request: Request, scope: str, subject: str = "") -> None:
    now = time.time()
    key = _rate_limit_key(request, scope, subject)
    cutoff = now - _AUTH_ATTEMPT_WINDOW_SECONDS
    attempts = [item for item in _AUTH_ATTEMPTS.get(key, []) if item >= cutoff]
    if len(attempts) >= _AUTH_ATTEMPT_LIMIT:
        raise HTTPException(status_code=429, detail={"error": "尝试次数过多，请稍后再试"})
    attempts.append(now)
    _AUTH_ATTEMPTS[key] = attempts


def _create_download_token(identity: dict[str, object]) -> str:
    now = time.time()
    expired = [key for key, (expires_at, _) in _DOWNLOAD_TOKENS.items() if expires_at < now]
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
            raise HTTPException(status_code=401, detail={"error": "下载链接已失效，请重新点击下载"})
        identity = item[1]
    else:
        identity = resolve_identity_for_request(request, authorization)
    if identity.get("role") != "admin":
        raise HTTPException(status_code=403, detail={"error": "需要管理员权限才能执行这个操作"})
    return identity


def _registration_enabled() -> bool:
    enabled = str(
        os.getenv("HAPPYIMAGE_REGISTRATION_ENABLED")
        or config.data.get("registration_enabled", "false")
    ).strip().lower()
    return enabled not in {"0", "false", "no", "off"}


def _normalize_register_name(body: RegisterRequest) -> str:
    name = (body.name or body.email or "").strip()
    if len(name) < 2:
        raise HTTPException(status_code=400, detail={"error": "账号名称至少需要 2 个字符"})
    if len(name) > 64:
        raise HTTPException(status_code=400, detail={"error": "账号名称不能超过 64 个字符"})
    if name.lower() in {"admin", "administrator", "root"}:
        raise HTTPException(status_code=400, detail={"error": "这个账号名称不可用于注册"})
    return name


def _normalize_register_password(body: RegisterRequest) -> str:
    password = (body.password or "").strip()
    confirm_password = (body.confirm_password or "").strip()
    if len(password) < 6:
        raise HTTPException(status_code=400, detail={"error": "密码至少需要 6 个字符"})
    if len(password) > 128:
        raise HTTPException(status_code=400, detail={"error": "密码不能超过 128 个字符"})
    if confirm_password and password != confirm_password:
        raise HTTPException(status_code=400, detail={"error": "两次输入的密码不一致"})
    return password


def create_router(app_version: str) -> APIRouter:
    router = APIRouter()

    @router.post("/auth/login")
    async def login(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        token = str(authorization or "").partition(" ")[2].strip()
        return _auth_login_response(identity, token, app_version)

    @router.post("/api/auth/login")
    async def password_login(request: Request, body: PasswordLoginRequest):
        access_key = body.access_key.strip()
        _check_auth_rate_limit(request, "access_key" if access_key else "password_login", access_key or body.email)
        if access_key:
            identity = require_identity(f"Bearer {access_key}")
            return _auth_login_response(identity, access_key, app_version)

        email = body.email.strip()
        password = body.password.strip()
        if not email or not password:
            raise HTTPException(status_code=400, detail={"error": "请输入账号和密码"})

        named_key_identity = _named_key_identity(email, password)
        if named_key_identity:
            return _auth_login_response(named_key_identity, password, app_version)

        expected_email = _configured_login_email()
        expected_password = _configured_login_password()
        if not expected_email or not expected_password:
            raise HTTPException(status_code=503, detail={"error": "登录服务尚未配置"})
        if email != expected_email or password != expected_password:
            test_login_token = _test_login_token(email, password)
            if test_login_token:
                try:
                    identity = require_identity(f"Bearer {test_login_token}")
                    return _auth_login_response(identity, test_login_token, app_version)
                except HTTPException:
                    pass
            raise HTTPException(status_code=401, detail={"error": "账号或密码不正确"})

        identity = require_identity(f"Bearer {config.auth_key}")
        return _auth_login_response(identity, config.auth_key, app_version)

    @router.post("/api/auth/register")
    async def register_user(request: Request, body: RegisterRequest):
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

    @router.get("/version")
    async def get_version():
        return {"version": app_version}

    @router.get("/api/settings")
    async def get_settings(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"config": config.get()}

    @router.post("/api/settings")
    async def save_settings(body: SettingsUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"config": config.update(body.model_dump(mode="python"))}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/images")
    async def get_images(request: Request, start_date: str = "", end_date: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return list_images(resolve_image_base_url(request), start_date=start_date.strip(), end_date=end_date.strip())

    @router.get("/images/{image_path:path}", include_in_schema=False)
    async def get_image(image_path: str, image_token: str = Query(default="", alias=IMAGE_ACCESS_TOKEN_PARAM)):
        verify_image_access_token(image_path, image_token)
        return get_image_response(image_path)

    @router.get("/image-thumbnails/{image_path:path}", include_in_schema=False)
    async def get_image_thumbnail(image_path: str, image_token: str = Query(default="", alias=IMAGE_ACCESS_TOKEN_PARAM)):
        verify_image_access_token(image_path, image_token)
        return get_thumbnail_response(image_path)

    @router.post("/api/images/delete")
    async def delete_images_endpoint(body: ImageDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return delete_images(body.paths, start_date=body.start_date.strip(), end_date=body.end_date.strip(), all_matching=body.all_matching)

    @router.post("/api/images/download")
    async def download_images_endpoint(body: ImageDownloadRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        buf = download_images_zip(body.paths)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="images.zip"'},
        )

    @router.post("/api/images/download-token")
    async def create_image_download_token(body: ImageDownloadTokenRequest, authorization: str | None = Header(default=None)):
        identity = require_admin(authorization)
        if not body.paths:
            raise HTTPException(status_code=400, detail={"error": "paths is required"})
        return {"token": _create_download_token(identity), "expires_in": _DOWNLOAD_TOKEN_TTL_SECONDS}

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
    async def get_logs(type: str = "", start_date: str = "", end_date: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"items": log_service.list(type=type.strip(), start_date=start_date.strip(), end_date=end_date.strip())}

    @router.post("/api/logs/delete")
    async def delete_logs(body: LogDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return log_service.delete(body.ids)

    @router.post("/api/proxy/test")
    async def test_proxy_endpoint(body: ProxyTestRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        candidate = (body.url or "").strip() or config.get_proxy_settings()
        if not candidate:
            raise HTTPException(status_code=400, detail={"error": "proxy url is required"})
        return {"result": await run_in_threadpool(test_proxy, candidate)}

    @router.get("/api/storage/info")
    async def get_storage_info(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        storage = config.get_storage_backend()
        return {
            "backend": storage.get_backend_info(),
            "health": storage.health_check(),
        }

    @router.post("/api/backup/test")
    async def test_backup_connection(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"result": await run_in_threadpool(backup_service.test_connection)}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/image-storage/test")
    async def test_image_storage_endpoint(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"result": await run_in_threadpool(image_storage_service.test_webdav)}

    @router.post("/api/image-storage/sync")
    async def sync_image_storage_endpoint(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"result": await run_in_threadpool(image_storage_service.sync_all)}
        except ImageStorageError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/backups")
    async def get_backups(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {
                "items": await run_in_threadpool(backup_service.list_backups),
                "state": backup_service.get_status(),
                "settings": backup_service.get_settings(),
            }
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/backups/run")
    async def run_backup_endpoint(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"result": await run_in_threadpool(backup_service.run_backup)}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/backups/delete")
    async def delete_backup_endpoint(body: BackupDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            await run_in_threadpool(backup_service.delete_backup, body.key)
            return {"ok": True}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/backups/detail")
    async def get_backup_detail(key: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"item": await run_in_threadpool(backup_service.get_backup_detail, key)}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/backups/download")
    async def download_backup_endpoint(key: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            item = await run_in_threadpool(backup_service.download_backup, key)
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        filename = str(item.get("name") or "backup.bin")
        quoted = quote(filename)
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
            "Content-Length": str(int(item.get("size") or 0)),
        }
        return Response(
            content=bytes(item.get("payload") or b""),
            media_type=str(item.get("content_type") or "application/octet-stream"),
            headers=headers,
        )


    @router.get("/api/images/tags")
    async def list_image_tags(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"tags": get_all_tags()}

    @router.post("/api/images/tags")
    async def update_image_tags(body: ImageTagsRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        rel = body.path.strip().lstrip("/")
        if not rel:
            raise HTTPException(status_code=400, detail={"error": "path is required"})
        tags = set_tags(rel, body.tags)
        return {"ok": True, "tags": tags}

    @router.delete("/api/images/tags/{tag}")
    async def delete_image_tag(tag: str, authorization: str | None = Header(default=None)):
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
        from services.account_service import account_service as acct_svc
        stats = acct_svc.get_stats()
        storage = config.get_storage_backend()
        storage_health = storage.health_check()
        healthy = stats["active"] > 0 or stats["unlimited_quota_count"] > 0

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
                "<!DOCTYPE html><html lang=\"zh\"><head><meta charset=\"UTF-8\">"
                "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                "<title>HappyImage Health</title></head><body>"
                f"<h1>HappyImage Health</h1><p>{status_text}</p>"
                f"<p>v{app_version}</p></body></html>"
            )

        require_admin(authorization)
        stats_json = {
            **public_json,
            "storage": {"backend": storage.get_backend_info(), "health": storage_health},
            "accounts": stats,
        }
        if format == "json":
            return stats_json
        return HTMLResponse(f"""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>号池健康监控 - HappyImage</title>
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
<h1><span class="status-dot {'status-ok' if healthy else 'status-degraded'}"></span>号池健康监控</h1>
<div style="font-size:13px;color:#94a3b8">v{app_version} · 30s 自动刷新</div>
</div>
<div class="container">
<div class="cards">
<div class="card"><div class="label">号池状态</div><div class="value {'green' if healthy else 'yellow'}">{'正常' if healthy else '异常'}</div></div>
<div class="card"><div class="label">当前账号</div><div class="value blue">{stats['total']}</div></div>
<div class="card"><div class="label">累计入库</div><div class="value">{stats['cumulative_total']}</div></div>
<div class="card"><div class="label">可用账号</div><div class="value green">{stats['active']}</div></div>
<div class="card"><div class="label">无限额</div><div class="value">{stats['unlimited_quota_count']}</div></div>
<div class="card"><div class="label">剩余额度</div><div class="value">{stats['total_quota']}</div></div>
<div class="card"><div class="label">限流</div><div class="value yellow">{stats['limited']}</div></div>
<div class="card"><div class="label">异常</div><div class="value red">{stats['abnormal']}</div></div>
<div class="card"><div class="label">禁用</div><div class="value">{stats['disabled']}</div></div>
<div class="card"><div class="label">成功/失败</div><div class="value">{stats['total_success']}<span style="font-size:18px;color:#94a3b8">/</span><span class="red">{stats['total_fail']}</span></div></div>
</div>
<h2 style="margin-bottom:12px;font-size:16px">账号类型分布</h2>
<table>
<tr><th>类型</th><th>数量</th></tr>
{''.join(f'<tr><td>{t}</td><td>{c}</td></tr>' for t,c in sorted(stats['by_type'].items()))}
</table>
<div class="refresh">JSON: <span class="api-url">/health?format=json</span></div>
</div></body></html>""")

    return router
