"""OIDC login routes for Happy Token web user authentication.

These routes handle the OIDC authorize redirect and callback flow.
They are separate from the OpenAI account OAuth import flow under
/api/accounts/oauth/*.
"""

from __future__ import annotations

import json
from urllib import error as urllib_error
from urllib import request as urllib_request

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from services.auth_service import auth_service
from services.config import config
from services import model_gateway_service
from services.newapi_binding_service import newapi_binding_service
from services.oidc_service import OIDCError, oidc_service
from services.web_session_service import web_session_service
from api.support import resolve_identity_for_request


class OIDCStartRequest(BaseModel):
    next_path: str = ""


class OIDCStartResponse(BaseModel):
    authorize_url: str


class ProviderTestRequest(BaseModel):
    type: str = ""
    protocol: str = "openai"
    base_url: str = ""
    models: list[str] = []
    api_key: str = ""


def _request_external_base_url(request: Request) -> str:
    configured = config.external_api_url
    if configured:
        return configured
    proto = (
        request.headers.get("x-forwarded-proto", request.url.scheme)
        .split(",", 1)[0]
        .strip()
    )
    host = (
        request.headers.get(
            "x-forwarded-host", request.headers.get("host", request.url.netloc)
        )
        .split(",", 1)[0]
        .strip()
    )
    if not host:
        return ""
    return f"{proto}://{host}".rstrip("/")


def _with_newapi_binding_status(
    identity: dict[str, object], binding: dict[str, object]
) -> dict[str, object]:
    next_identity = dict(identity)
    next_identity["newapi_binding_status"] = str(
        binding.get("status") or ("configured" if binding.get("ok") else "pending")
    )
    next_identity["newapi_management_url"] = str(
        binding.get("management_url") or ""
    ).strip()
    message = str(binding.get("message") or "").strip()
    if message:
        next_identity["newapi_binding_message"] = message
    return next_identity


def _newapi_session_fields(identity: dict[str, object]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for key in (
        "model_provider",
        "model_base_url",
        "newapi_binding_status",
        "newapi_binding_message",
        "newapi_management_url",
    ):
        value = str(identity.get(key) or "").strip()
        if value:
            fields[key] = value
    model_providers = identity.get("model_providers")
    if isinstance(model_providers, list):
        fields["model_providers"] = model_providers
    if identity.get("model_api_key_configured") is not None:
        fields["model_api_key_configured"] = bool(
            identity.get("model_api_key_configured")
        )
    return fields


def _newapi_binding_identity_fields(identity: dict[str, object]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for key in (
        "newapi_binding_status",
        "newapi_binding_message",
        "newapi_management_url",
    ):
        value = str(identity.get(key) or "").strip()
        if value:
            fields[key] = value
    return fields


def _stored_newapi_binding_fields(user_item: dict[str, object]) -> dict[str, object]:
    provider = str(user_item.get("model_provider") or "").strip().lower()
    if provider != "newapi" or not bool(user_item.get("model_api_key_configured")):
        return {}
    return {
        "newapi_binding_status": "configured",
        "newapi_management_url": config.get_newapi_binding_settings().get(
            "management_url", ""
        ),
    }


def _ensure_newapi_binding_for_user(
    user_item: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    auth_provider = str(user_item.get("auth_provider") or "").strip()
    auth_subject = str(user_item.get("auth_subject") or "").strip()
    if not auth_subject:
        return user_item, {}
    binding = newapi_binding_service.ensure_default_token(
        provider=auth_provider or "oidc",
        subject=auth_subject,
        email=str(user_item.get("email") or ""),
        name=str(user_item.get("name") or ""),
    )
    if not binding.get("ok"):
        return user_item, _with_newapi_binding_status({}, binding)
    try:
        updated_user = auth_service.apply_newapi_default_provider(
            str(user_item.get("id") or ""),
            base_url=str(binding.get("base_url") or ""),
            api_key=str(binding.get("token") or ""),
        )
        if updated_user is not None:
            user_item = updated_user
    except ValueError:
        binding = {
            **binding,
            "ok": False,
            "status": "failed",
            "message": "NewAPI 默认供应商配置不完整",
        }
        return user_item, _with_newapi_binding_status({}, binding)
    return user_item, _with_newapi_binding_status({}, binding)


def _create_session_with_identity_fields(
    identity: dict[str, object],
) -> tuple[str, str]:
    payload = web_session_service.create_session_payload(identity)
    payload.update(_newapi_session_fields(identity))
    token = web_session_service.sign_session(payload)
    cookie = web_session_service.make_set_cookie_header(token)
    return token, cookie


def _session_newapi_fields(
    request: Request, *, expected_user_id: str
) -> dict[str, object]:
    cookie_value = request.cookies.get(web_session_service.cookie_name, "")
    if not cookie_value:
        return {}
    try:
        payload = web_session_service.verify_session(cookie_value)
    except Exception:
        return {}
    if str(payload.get("sub") or "").strip() != expected_user_id:
        return {}
    return _newapi_session_fields(payload)


def _test_model_provider_connection(body: ProviderTestRequest) -> dict[str, object]:
    base_url = body.base_url.strip().rstrip("/")
    api_key = body.api_key.strip()
    if not base_url:
        raise ValueError("Base URL 不能为空")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("Base URL 必须以 http:// 或 https:// 开头")
    if not api_key:
        raise ValueError("API Key 不能为空")

    req = urllib_request.Request(
        f"{base_url}/models",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib_request.urlopen(req, timeout=20) as response:
            status = int(getattr(response, "status", 200))
            raw_body = response.read(1024 * 512)
    except urllib_error.HTTPError as exc:
        detail = "供应商连接失败"
        try:
            payload = json.loads(exc.read(4096).decode("utf-8", "ignore"))
            if isinstance(payload, dict):
                error_value = payload.get("error")
                if isinstance(error_value, dict):
                    detail = str(error_value.get("message") or detail)
                elif isinstance(error_value, str):
                    detail = error_value
        except Exception:
            detail = f"供应商连接失败: HTTP {exc.code}"
        raise ValueError(detail) from exc
    except Exception as exc:
        raise ValueError("供应商连接失败，请检查 Base URL 和 API Key") from exc

    if status < 200 or status >= 300:
        raise ValueError(f"供应商连接失败: HTTP {status}")

    models: list[str] = []
    try:
        payload = json.loads(raw_body.decode("utf-8", "ignore"))
        data = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    model_id = str(item.get("id") or "").strip()
                else:
                    model_id = str(item or "").strip()
                if model_id and model_id not in models:
                    models.append(model_id)
    except Exception:
        models = []

    configured_models = [
        str(model).strip()
        for model in body.models
        if str(model).strip() and str(model).strip() not in models
    ]
    return {"ok": True, "models": models[:80] or configured_models[:80]}


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/auth/oidc/start")
    async def oidc_start(body: OIDCStartRequest, request: Request):
        """Start OIDC login: return the provider authorize URL.

        The frontend calls this to get a URL, then navigates the user's
        browser to it.
        """
        if not oidc_service.is_enabled():
            raise HTTPException(
                status_code=400,
                detail={"error": "OIDC 登录尚未启用"},
            )
        try:
            result = await run_in_threadpool(
                oidc_service.build_authorize_url,
                next_path=body.next_path,
                api_base_url=_request_external_base_url(request),
            )
        except OIDCError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return result

    @router.get("/api/auth/oidc/callback")
    async def oidc_callback(request: Request, code: str = "", state: str = ""):
        """OIDC provider redirects here after user authentication.

        Validates the callback, exchanges the code, creates/finds the user,
        creates a web session, and redirects to the frontend.
        """
        if not oidc_service.is_enabled():
            raise HTTPException(
                status_code=400,
                detail={"error": "OIDC 登录尚未启用"},
            )

        error = request.query_params.get("error", "").strip()
        if error:
            error_desc = request.query_params.get("error_description", error)
            raise HTTPException(
                status_code=400,
                detail={"error": f"OIDC 登录失败: {error_desc}"},
            )

        try:
            oidc_claims = await run_in_threadpool(
                oidc_service.handle_callback,
                code=code,
                state=state,
            )
        except OIDCError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

        # Find or create the Happy Token user bound to this OIDC identity
        try:
            user_item = await run_in_threadpool(
                auth_service.find_or_create_oidc_user,
                auth_provider="oidc",
                auth_subject=oidc_claims["sub"],
                email=oidc_claims.get("email", ""),
                name=oidc_claims.get("name", ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=403, detail={"error": str(exc)}) from exc

        binding = await run_in_threadpool(
            newapi_binding_service.ensure_default_token,
            provider="casdoor",
            subject=str(oidc_claims.get("sub") or ""),
            email=str(oidc_claims.get("email") or ""),
            name=str(oidc_claims.get("name") or ""),
        )
        if binding.get("ok"):
            try:
                updated_user = await run_in_threadpool(
                    auth_service.apply_newapi_default_provider,
                    str(user_item.get("id") or ""),
                    base_url=str(binding.get("base_url") or ""),
                    api_key=str(binding.get("token") or ""),
                )
                if updated_user is not None:
                    user_item = updated_user
            except ValueError:
                binding = {
                    **binding,
                    "ok": False,
                    "status": "failed",
                    "message": "NewAPI 默认供应商配置不完整",
                }

        # Create web session
        identity = {
            "id": user_item.get("id", ""),
            "name": user_item.get("name", ""),
            "role": user_item.get("role", "user"),
            "watermark_label": user_item.get("watermark_label") or "",
            "watermark_unlocked": bool(user_item.get("watermark_unlocked", False)),
            "model_provider": user_item.get("model_provider") or "",
            "model_base_url": user_item.get("model_base_url") or "",
            "model_api_key_configured": bool(user_item.get("model_api_key_configured")),
            "model_providers": (
                user_item.get("model_providers")
                if isinstance(user_item.get("model_providers"), list)
                else []
            ),
            "preferences": (
                user_item.get("preferences")
                if isinstance(user_item.get("preferences"), dict)
                else {}
            ),
        }
        identity.update(
            auth_service.get_model_gateway_config(str(user_item.get("id") or ""))
        )
        for key in ("auth_provider", "auth_subject", "email"):
            value = str(user_item.get(key) or "").strip()
            if value:
                identity[key] = value
        identity = _with_newapi_binding_status(identity, binding)
        _token, cookie = _create_session_with_identity_fields(identity)

        # Redirect to frontend
        frontend_base = config.public_app_url or "/"
        next_path = oidc_claims.get("next_path", "") or "/image"
        if not next_path.startswith("/"):
            next_path = "/image"
        redirect_url = f"{frontend_base.rstrip('/')}{next_path}"

        response = RedirectResponse(url=redirect_url, status_code=302)
        response.headers["Set-Cookie"] = cookie
        return response

    @router.get("/api/auth/session")
    async def get_session(
        request: Request, authorization: str | None = Header(default=None)
    ):
        """Return the current user session from the session cookie or Bearer token.

        Returns 401 if no valid session is present.
        """
        identity = resolve_identity_for_request(request, authorization)

        # Verify the user still exists and is enabled
        user_id = str(identity.get("id") or "")
        user_item = auth_service.get_key(user_id)
        if user_item is None:
            raise HTTPException(status_code=401, detail={"error": "账号不存在"})
        if not bool(user_item.get("enabled", True)):
            raise HTTPException(status_code=401, detail={"error": "账号已被禁用"})

        # Refresh identity from current user data
        stored_newapi_fields = _stored_newapi_binding_fields(user_item)
        session_newapi_fields = {
            **_newapi_binding_identity_fields(identity),
            **_newapi_binding_identity_fields(
                _session_newapi_fields(request, expected_user_id=user_id)
            ),
        }
        if stored_newapi_fields.get("newapi_binding_status") != "configured":
            user_item, refreshed_newapi_fields = await run_in_threadpool(
                _ensure_newapi_binding_for_user, user_item
            )
            if refreshed_newapi_fields:
                session_newapi_fields = {
                    **session_newapi_fields,
                    **_newapi_binding_identity_fields(refreshed_newapi_fields),
                }
            stored_newapi_fields = _stored_newapi_binding_fields(user_item)
        if stored_newapi_fields.get("newapi_binding_status") == "configured":
            session_newapi_fields = {
                **session_newapi_fields,
                **stored_newapi_fields,
            }
            session_newapi_fields.pop("newapi_binding_message", None)
        identity = {
            "id": user_item.get("id", ""),
            "name": user_item.get("name", ""),
            "role": user_item.get("role", "user"),
            "watermark_label": user_item.get("watermark_label") or "",
            "watermark_unlocked": bool(user_item.get("watermark_unlocked", False)),
            "model_provider": user_item.get("model_provider") or "",
            "model_base_url": user_item.get("model_base_url") or "",
            "model_api_key_configured": bool(user_item.get("model_api_key_configured")),
            "model_providers": (
                user_item.get("model_providers")
                if isinstance(user_item.get("model_providers"), list)
                else []
            ),
            "preferences": (
                user_item.get("preferences")
                if isinstance(user_item.get("preferences"), dict)
                and user_item.get("preferences")
                else (
                    identity.get("preferences")
                    if isinstance(identity.get("preferences"), dict)
                    else {}
                )
            ),
        }
        identity.update(auth_service.get_model_gateway_config(user_id))
        for key in ("auth_provider", "auth_subject", "email"):
            value = str(user_item.get(key) or "").strip()
            if value:
                identity[key] = value
        for key, value in session_newapi_fields.items():
            if value != "":
                identity[key] = value
        if identity.get("newapi_binding_status") == "configured":
            identity.pop("newapi_binding_message", None)

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
        model_api_key_configured = bool(
            identity.get("model_api_key_configured")
        ) or bool(str(identity.get("model_api_key") or "").strip())
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
            for key in (
                "auth_provider",
                "auth_subject",
                "email",
                "newapi_binding_status",
                "newapi_binding_message",
                "newapi_management_url",
            )
            if str(identity.get(key) or "").strip()
        }

        return {
            "ok": True,
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

    @router.post("/api/auth/provider-test")
    async def provider_test(
        body: ProviderTestRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        """Test a user-supplied OpenAI-compatible provider without saving it."""
        resolve_identity_for_request(request, authorization)
        try:
            return await run_in_threadpool(_test_model_provider_connection, body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/auth/newapi-management")
    async def newapi_management(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        """Return the current user's HappyToken/NewAPI management data."""
        identity = resolve_identity_for_request(request, authorization)
        user_id = str(identity.get("id") or "")
        user_item = auth_service.get_key(user_id)
        if user_item is None:
            raise HTTPException(status_code=401, detail={"error": "账号不存在"})
        if not bool(user_item.get("enabled", True)):
            raise HTTPException(status_code=401, detail={"error": "账号已被禁用"})

        user_item, binding_fields = await run_in_threadpool(
            _ensure_newapi_binding_for_user, user_item
        )
        binding_status = str(
            binding_fields.get("newapi_binding_status")
            or _stored_newapi_binding_fields(user_item).get("newapi_binding_status")
            or "pending"
        )
        binding_message = str(binding_fields.get("newapi_binding_message") or "")
        management_url = str(
            binding_fields.get("newapi_management_url")
            or config.get_newapi_binding_settings().get("management_url")
            or ""
        ).strip()
        auth_provider = str(user_item.get("auth_provider") or "").strip()
        auth_subject = str(user_item.get("auth_subject") or "").strip()
        binding = await run_in_threadpool(
            newapi_binding_service.ensure_default_token,
            auth_provider or "oidc",
            auth_subject,
            str(user_item.get("email") or ""),
            str(user_item.get("name") or ""),
        )
        if binding.get("ok"):
            binding_status = "configured"
            binding_message = ""
            management_url = str(binding.get("management_url") or management_url)
        elif binding.get("message"):
            binding_status = str(binding.get("status") or "failed")
            binding_message = str(binding.get("message") or "")

        return {
            "ok": binding_status == "configured",
            "status": binding_status,
            "message": binding_message,
            "management_url": management_url,
            "newapi_user_id": str(binding.get("user_id") or ""),
            "tokens": binding.get("tokens") if isinstance(binding.get("tokens"), list) else [],
        }

    @router.post("/api/auth/logout")
    async def logout():
        """Clear the web session cookie."""
        from fastapi.responses import JSONResponse

        cookie = web_session_service.make_clear_cookie_header()
        response = JSONResponse(content={"ok": True})
        response.headers["Set-Cookie"] = cookie
        return response

    return router
