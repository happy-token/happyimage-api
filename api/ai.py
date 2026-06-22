from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from api.image_inputs import parse_image_edit_request, read_image_sources
from api.support import require_identity, resolve_image_base_url
from services.content_filter import check_request
from services.log_service import LoggedCall
from services.protocol import openai_v1_models
from services import model_gateway_service


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: str = "gpt-image-2"
    n: int = Field(default=1, ge=1, le=4)
    size: str | None = None
    quality: str = "auto"
    response_format: str = "b64_json"
    history_disabled: bool = True
    stream: bool | None = None


async def filter_or_log(call: LoggedCall, text: str) -> None:
    try:
        await run_in_threadpool(check_request, text)
    except HTTPException as exc:
        call.log("调用失败", status="failed", error=str(exc.detail))
        raise


def _apply_identity_model_gateway(payload: dict[str, object], identity: dict[str, object]) -> None:
    base_url = str(identity.get("model_base_url") or "").strip().rstrip("/")
    api_key = str(identity.get("model_api_key") or "").strip()
    if base_url and api_key:
        payload["model_gateway_provider"] = str(identity.get("model_provider") or "newapi").strip() or "newapi"
        payload["model_gateway_base_url"] = base_url
        payload["model_gateway_api_key"] = api_key


def _ensure_identity_model_gateway(payload: dict[str, object]) -> None:
    if not payload.get("model_gateway_base_url") or not payload.get("model_gateway_api_key"):
        raise HTTPException(status_code=400, detail={"error": "请先在用户设置中配置模型供应商 Base URL 和 API Key"})


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/v1/models")
    async def list_models(authorization: str | None = Header(default=None)):
        require_identity(authorization)
        try:
            return await run_in_threadpool(openai_v1_models.list_models)
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc

    @router.post("/v1/images/generations")
    async def generate_images(
            body: ImageGenerationRequest,
            request: Request,
            authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        payload = body.model_dump(mode="python")
        payload["base_url"] = resolve_image_base_url(request)
        payload["owner_id"] = str(identity.get("id") or "")
        _apply_identity_model_gateway(payload, identity)
        _ensure_identity_model_gateway(payload)
        call = LoggedCall(identity, "/v1/images/generations", body.model, "文生图", request_text=body.prompt)
        await filter_or_log(call, body.prompt)
        return await call.run(model_gateway_service.generate_image, payload)

    @router.post("/v1/images/edits")
    async def edit_images(
            request: Request,
            authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        payload, image_sources = await parse_image_edit_request(request)
        prompt = str(payload["prompt"])
        model = str(payload["model"])
        call = LoggedCall(identity, "/v1/images/edits", model, "图生图", request_text=prompt)
        await filter_or_log(call, prompt)
        payload["images"] = await read_image_sources(image_sources)
        payload["base_url"] = resolve_image_base_url(request)
        payload["owner_id"] = str(identity.get("id") or "")
        _apply_identity_model_gateway(payload, identity)
        _ensure_identity_model_gateway(payload)
        return await call.run(model_gateway_service.edit_image, payload)

    return router
