"""OIDC login routes for HappyImage web user authentication.

These routes handle the OIDC authorize redirect and callback flow.
They are separate from the OpenAI account OAuth import flow under
/api/accounts/oauth/*.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from services.auth_service import auth_service
from services.config import config
from services.oidc_service import OIDCError, oidc_service
from services.web_session_service import web_session_service


class OIDCStartRequest(BaseModel):
    next_path: str = ""


class OIDCStartResponse(BaseModel):
    authorize_url: str


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/auth/oidc/start")
    async def oidc_start(body: OIDCStartRequest):
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

        # Find or create the HappyImage user bound to this OIDC identity
        oidc_settings = config.get_oidc_settings()
        default_quota = int(oidc_settings.get("default_image_quota", 0))
        try:
            user_item = await run_in_threadpool(
                auth_service.find_or_create_oidc_user,
                auth_provider="oidc",
                auth_subject=oidc_claims["sub"],
                email=oidc_claims.get("email", ""),
                name=oidc_claims.get("name", ""),
                default_image_quota=default_quota,
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
            "image_quota": user_item.get("image_quota"),
        }
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
    async def get_session(request: Request):
        """Return the current user session from the session cookie.

        Returns 401 if no valid session is present.
        """
        cookie_value = request.cookies.get(web_session_service.cookie_name, "")
        if not cookie_value:
            raise HTTPException(status_code=401, detail={"error": "未登录"})

        from services.web_session_service import WebSessionError
        try:
            identity = web_session_service.resolve_identity(cookie_value)
        except WebSessionError as exc:
            raise HTTPException(
                status_code=401, detail={"error": str(exc)}
            ) from exc

        # Verify the user still exists and is enabled
        user_id = str(identity.get("id") or "")
        user_item = auth_service.get_key(user_id)
        if user_item is None and user_id == "admin" and identity.get("role") == "admin" and config.auth_key:
            user_item = {"id": "admin", "name": "管理员", "role": "admin", "enabled": True}
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
            "image_quota": user_item.get("image_quota"),
        }

        role = "admin" if identity.get("role") == "admin" else "user"
        subject_id = str(identity.get("id") or "").strip() or role
        name = str(identity.get("name") or "").strip() or ("管理员" if role == "admin" else "创作者")
        image_quota = identity.get("image_quota") if role == "user" else None

        return {
            "ok": True,
            "role": role,
            "subject_id": subject_id,
            "name": name,
            "image_quota": image_quota,
            "user": {
                "id": subject_id,
                "name": name,
                "role": role,
                "image_quota": image_quota,
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
