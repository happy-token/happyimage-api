from __future__ import annotations

import hmac
from urllib.parse import urlencode

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict

from api.support import require_identity
from services.auth_service import auth_service
from services.config import config
from services.log_service import LOG_TYPE_USER_QUOTA, log_service


class NewAPIRechargeWebhookRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = ""
    order_id: str = ""
    happyimage_user_id: str = ""
    external_subject: str = ""
    auth_provider: str = "oidc"
    email: str = ""
    amount: int | float | str | None = None
    quota: int | str | None = None


def _clean(value: object) -> str:
    return str(value or "").strip()


def _request_base_url(request: Request) -> str:
    return config.frontend_base_url or config.base_url or f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"


def _build_newapi_recharge_url(identity: dict[str, object], request: Request, settings: dict[str, object]) -> str:
    base_url = _clean(settings.get("newapi_base_url")).rstrip("/")
    if not base_url:
        return ""
    path = _clean(settings.get("newapi_console_topup_path")) or "/console/topup"
    if not path.startswith("/"):
        path = f"/{path}"
    query = {
        "source": "happyimage",
        "return_url": f"{_request_base_url(request).rstrip('/')}/image",
    }
    user_id = _clean(identity.get("id"))
    if user_id:
        query["happyimage_user_id"] = user_id
    subject = _clean(identity.get("auth_subject"))
    if subject:
        query["external_subject"] = subject
    email = _clean(identity.get("email"))
    if email:
        query["email"] = email
    separator = "&" if "?" in path else "?"
    return f"{base_url}{path}{separator}{urlencode(query)}"


def _resolve_webhook_user(body: NewAPIRechargeWebhookRequest) -> dict[str, object] | None:
    user_id = _clean(body.happyimage_user_id)
    if user_id:
        item = auth_service.get_key(user_id, role="user")
        if item is not None:
            return item
    external_subject = _clean(body.external_subject)
    if external_subject:
        item = auth_service.find_by_oidc_binding(_clean(body.auth_provider) or "oidc", external_subject)
        if item is not None:
            return item
    email = _clean(body.email)
    if email:
        return auth_service.find_by_email(email)
    return None


def _quota_delta(body: NewAPIRechargeWebhookRequest, settings: dict[str, object]) -> int:
    if body.quota is not None:
        try:
            return max(0, int(body.quota))
        except (TypeError, ValueError):
            return 0
    try:
        amount = float(body.amount or 0)
    except (TypeError, ValueError):
        amount = 0
    return max(0, int(amount * int(settings.get("quota_per_unit") or 1)))


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/recharge/session")
    async def get_recharge_session(request: Request, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization, request)
        settings = config.get_recharge_settings()
        provider = _clean(settings.get("provider")) or "contact"
        enabled = bool(settings.get("enabled"))
        response: dict[str, object] = {
            "enabled": enabled,
            "provider": provider,
            "mode": "contact",
            "quota": identity.get("image_quota"),
        }
        if enabled and provider == "newapi":
            recharge_url = _build_newapi_recharge_url(identity, request, settings)
            if recharge_url:
                response.update(
                    {
                        "mode": "redirect",
                        "recharge_url": recharge_url,
                        "message": "前往 New API 充值中心完成支付，支付成功后额度将同步到 HappyImage。",
                    }
                )
                return response
        response["message"] = "当前未配置在线充值，请联系管理员开通或手动充值。"
        return response

    @router.post("/api/recharge/newapi/webhook")
    async def receive_newapi_webhook(
        body: NewAPIRechargeWebhookRequest,
        x_happyimage_recharge_secret: str | None = Header(default=None),
    ):
        settings = config.get_recharge_settings()
        secret = _clean(settings.get("webhook_secret"))
        if not secret:
            raise HTTPException(status_code=404, detail={"error": "充值回调未启用"})
        provided = _clean(x_happyimage_recharge_secret)
        if not provided or not hmac.compare_digest(provided, secret):
            raise HTTPException(status_code=401, detail={"error": "充值回调密钥无效"})
        status = _clean(body.status).lower()
        if status not in {"paid", "success", "completed", "complete"}:
            return {"ok": True, "ignored": True, "reason": "status_not_paid"}
        delta = _quota_delta(body, settings)
        if delta <= 0:
            raise HTTPException(status_code=400, detail={"error": "回调额度必须大于 0"})
        user = await run_in_threadpool(_resolve_webhook_user, body)
        if user is None:
            raise HTTPException(status_code=404, detail={"error": "找不到对应的 HappyImage 用户"})
        before = user.get("image_quota")
        after = None if before is None else max(0, int(before)) + delta
        updated = await run_in_threadpool(auth_service.update_key, str(user.get("id") or ""), {"image_quota": after}, role="user")
        if updated is None:
            raise HTTPException(status_code=404, detail={"error": "用户不存在或已不可用"})
        log_service.add(
            LOG_TYPE_USER_QUOTA,
            "New API 充值同步",
            {
                "action": "newapi_recharge",
                "user_id": updated.get("id"),
                "user_name": updated.get("name"),
                "order_id": _clean(body.order_id),
                "amount": delta,
                "before_quota": before,
                "after_quota": updated.get("image_quota"),
            },
        )
        return {"ok": True, "user_id": updated.get("id"), "image_quota": updated.get("image_quota")}

    return router
