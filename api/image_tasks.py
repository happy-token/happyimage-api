from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from api.image_inputs import parse_image_edit_request, read_image_sources
from api.support import require_identity, resolve_image_base_url
from services.content_filter import check_request
from services.image_task_service import image_task_service
from services.log_service import LoggedCall


class ImageGenerationTaskRequest(BaseModel):
    client_task_id: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    model: str = "gpt-image-2"
    size: str | None = None
    quality: str = "auto"
    client_conversation_id: str | None = None
    client_turn_id: str | None = None
    client_image_id: str | None = None


class ImageFeedbackRequest(BaseModel):
    image_index: int = Field(default=0, ge=0)
    vote: str | None = None


def _parse_task_ids(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def prompt_requires_reference_image(prompt: str) -> bool:
    import re

    normalized = str(prompt or "").strip()
    return any(
        re.search(pattern, normalized, re.IGNORECASE)
        for pattern in (
            r"\b(attached|uploaded|source)\s+(image|photo|picture|face|portrait)\b",
            r"\b(this|that|the)\s+(image|photo|picture)\b",
            r"\b(image|photo|picture|face|portrait)\s+(?:as|for|from|with)\s+(?:a\s+|the\s+)?(?:facial\s+|face\s+|identity\s+)?reference\b",
            r"参考图|上传(?:的)?(?:图片|照片)|源图|原图|这张图|该图片|以.*(?:图片|照片).*参考|参考.*(?:图片|照片)",
        )
    )


async def filter_or_log(call: LoggedCall, text: str) -> None:
    try:
        await run_in_threadpool(check_request, text)
    except HTTPException as exc:
        call.log("调用失败", status="failed", error=str(exc.detail))
        raise


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/image-tasks")
    async def list_image_tasks(
        request: Request,
        ids: str = Query(default=""),
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization, request)
        return await run_in_threadpool(image_task_service.list_tasks, identity, _parse_task_ids(ids))

    @router.post("/api/image-tasks/generations")
    async def create_generation_task(
        body: ImageGenerationTaskRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization, request)
        if prompt_requires_reference_image(body.prompt):
            raise HTTPException(
                status_code=400,
                detail={"error": "请先上传参考图，包含参考图要求的提示词需要使用图生图。"},
            )
        await filter_or_log(LoggedCall(identity, "/api/image-tasks/generations", body.model, "文生图任务", request_text=body.prompt), body.prompt)
        try:
            return await run_in_threadpool(
                image_task_service.submit_generation,
                identity,
                client_task_id=body.client_task_id,
                prompt=body.prompt,
                model=body.model,
                size=body.size,
                quality=body.quality,
                base_url=resolve_image_base_url(request),
                client_conversation_id=body.client_conversation_id or "",
                client_turn_id=body.client_turn_id or "",
                client_image_id=body.client_image_id or "",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/image-tasks/edits")
    async def create_edit_task(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization, request)
        payload, image_sources = await parse_image_edit_request(request)
        client_task_id = str(payload.get("client_task_id") or "").strip()
        if not client_task_id:
            raise HTTPException(status_code=400, detail={"error": "client_task_id is required"})
        prompt = str(payload["prompt"])
        model = str(payload["model"])
        await filter_or_log(LoggedCall(identity, "/api/image-tasks/edits", model, "图生图任务", request_text=prompt), prompt)
        images = await read_image_sources(image_sources)
        try:
            return await run_in_threadpool(
                image_task_service.submit_edit,
                identity,
                client_task_id=client_task_id,
                prompt=prompt,
                model=model,
                size=payload["size"],
                quality=payload["quality"],
                base_url=resolve_image_base_url(request),
                images=images,
                client_conversation_id=str(payload.get("client_conversation_id") or ""),
                client_turn_id=str(payload.get("client_turn_id") or ""),
                client_image_id=str(payload.get("client_image_id") or ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/image-tasks/{task_id}/feedback")
    async def update_image_feedback(
        task_id: str,
        body: ImageFeedbackRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization, request)
        try:
            return await run_in_threadpool(
                image_task_service.set_image_feedback,
                identity,
                task_id=task_id,
                image_index=body.image_index,
                vote=body.vote,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    return router
