"""OIDC login routes for Happy Token web user authentication.

These routes handle the OIDC authorize redirect and callback flow.
They are separate from the OpenAI account OAuth import flow under
/api/accounts/oauth/*.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from services.auth_service import auth_service
from services.config import config
from services import model_gateway_service
from services.oidc_service import OIDCError, oidc_service
from services.web_session_service import web_session_service
from api.support import resolve_identity_for_request


class OIDCStartRequest(BaseModel):
    next_path: str = ""


class OIDCStartResponse(BaseModel):
    authorize_url: str


def _request_external_base_url(request: Request) -> str:
    configured = config.api_base_url
    if configured:
        return configured
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",", 1)[0].strip()
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc)).split(",", 1)[0].strip()
    if not host:
        return ""
    return f"{proto}://{host}".rstrip("/")


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
            raise HTTPException(
                status_code=400, detail={"error": str(exc)}
            ) from exc
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
            raise HTTPException(
                status_code=400, detail={"error": str(exc)}
            ) from exc

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
            raise HTTPException(
                status_code=403, detail={"error": str(exc)}
            ) from exc

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
            "model_providers": user_item.get("model_providers") if isinstance(user_item.get("model_providers"), list) else [],
            "preferences": user_item.get("preferences") if isinstance(user_item.get("preferences"), dict) else {},
        }
        identity.update(auth_service.get_model_gateway_config(str(user_item.get("id") or "")))
        for key in ("auth_provider", "auth_subject", "email"):
            value = str(user_item.get(key) or "").strip()
            if value:
                identity[key] = value
        _token, cookie = web_session_service.create_session(identity)

        # Redirect to frontend
        frontend_base = config.frontend_base_url or "/"
        next_path = oidc_claims.get("next_path", "") or "/image"
        if not next_path.startswith("/"):
            next_path = "/image"
        redirect_url = f"{frontend_base.rstrip('/')}{next_path}"

        response = RedirectResponse(url=redirect_url, status_code=302)
        response.headers["Set-Cookie"] = cookie
        return response

    @router.get("/api/auth/session")
    async def get_session(request: Request, authorization: str | None = Header(default=None)):
        """Return the current user session from the session cookie or Bearer token.

        Returns 401 if no valid session is present.
        """
        identity = resolve_identity_for_request(request, authorization)

        # Verify the user still exists and is enabled
        user_id = str(identity.get("id") or "")
        user_item = auth_service.get_key(user_id)
        if user_item is None:
            raise HTTPException(
                status_code=401, detail={"error": "账号不存在"}
            )
        if not bool(user_item.get("enabled", True)):
            raise HTTPException(
                status_code=401, detail={"error": "账号已被禁用"}
            )

        # Refresh identity from current user data
        identity = {
            "id": user_item.get("id", ""),
            "name": user_item.get("name", ""),
            "role": user_item.get("role", "user"),
            "watermark_label": user_item.get("watermark_label") or "",
            "watermark_unlocked": bool(user_item.get("watermark_unlocked", False)),
            "model_provider": user_item.get("model_provider") or "",
            "model_base_url": user_item.get("model_base_url") or "",
            "model_api_key_configured": bool(user_item.get("model_api_key_configured")),
            "model_providers": user_item.get("model_providers") if isinstance(user_item.get("model_providers"), list) else [],
            "preferences": (
                user_item.get("preferences")
                if isinstance(user_item.get("preferences"), dict) and user_item.get("preferences")
                else identity.get("preferences")
                if isinstance(identity.get("preferences"), dict)
                else {}
            ),
        }
        identity.update(auth_service.get_model_gateway_config(user_id))
        for key in ("auth_provider", "auth_subject", "email"):
            value = str(user_item.get(key) or "").strip()
            if value:
                identity[key] = value

        role = "admin" if identity.get("role") == "admin" else "user"
        subject_id = str(identity.get("id") or "").strip() or role
        name = str(identity.get("name") or "").strip() or ("管理员" if role == "admin" else "创作者")
        watermark_label = str(identity.get("watermark_label") or "").strip()
        watermark_unlocked = role == "admin" or bool(identity.get("watermark_unlocked", False))
        model_provider = str(identity.get("model_provider") or "").strip()
        model_base_url = str(identity.get("model_base_url") or "").strip().rstrip("/")
        model_api_key_configured = bool(identity.get("model_api_key_configured")) or bool(str(identity.get("model_api_key") or "").strip())
        model_gateway_enabled = model_gateway_service.is_enabled(model_base_url, str(identity.get("model_api_key") or ""))
        model_providers = identity.get("model_providers") if isinstance(identity.get("model_providers"), list) else []
        preferences = identity.get("preferences") if isinstance(identity.get("preferences"), dict) else {}
        external_identity = {
            key: str(identity.get(key) or "").strip()
            for key in ("auth_provider", "auth_subject", "email")
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

    @router.post("/api/auth/logout")
    async def logout():
        """Clear the web session cookie."""
        from fastapi.responses import JSONResponse
        cookie = web_session_service.make_clear_cookie_header()
        response = JSONResponse(content={"ok": True})
        response.headers["Set-Cookie"] = cookie
        return response

    return router
