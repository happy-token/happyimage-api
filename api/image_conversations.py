from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from api.support import require_identity
from services.image_conversation_service import image_conversation_service


class ConversationUpsertRequest(BaseModel):
    title: str = ""


class TurnCreateRequest(BaseModel):
    id: str = Field(..., min_length=1)
    prompt: str = ""
    model: str = "gpt-image-2"
    mode: str = "generate"
    referenceImages: list[dict[str, Any]] = Field(default_factory=list)
    count: int = Field(default=1, ge=1)
    size: str = ""
    ratio: str = "1:1"
    tier: str = "1k"
    quality: str = "auto"
    images: list[dict[str, Any]] = Field(default_factory=list)
    createdAt: str = ""
    status: str = "queued"


class TurnPatchRequest(BaseModel):
    prompt: str | None = None
    status: str | None = None
    error: str | None = None
    promptDeleted: bool | None = None
    resultsDeleted: bool | None = None


class ResultPatchRequest(BaseModel):
    taskId: str | None = None
    status: str | None = None
    taskStatus: str | None = None
    progress: str | None = None
    url: str | None = None
    revised_prompt: str | None = None
    error: str | None = None
    durationMs: int | None = None
    feedback: dict[str, Any] | None = Field(default=None)


def _patch_dict(model: BaseModel) -> dict[str, Any]:
    return {key: value for key, value in model.model_dump().items() if value is not None}


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/image-conversations")
    async def list_image_conversations(request: Request, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization, request)
        items = await run_in_threadpool(image_conversation_service.list_conversations, identity)
        return {"items": items}

    @router.put("/api/image-conversations/{conversation_id}")
    async def upsert_image_conversation(
        conversation_id: str,
        body: ConversationUpsertRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization, request)
        try:
            item = await run_in_threadpool(
                image_conversation_service.upsert_conversation,
                identity,
                conversation_id=conversation_id,
                title=body.title,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
        return {"item": item}

    @router.post("/api/image-conversations/{conversation_id}/turns")
    async def create_image_conversation_turn(
        conversation_id: str,
        body: TurnCreateRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization, request)
        try:
            item = await run_in_threadpool(
                image_conversation_service.create_turn,
                identity,
                conversation_id=conversation_id,
                turn=body.model_dump(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
        return {"item": item}

    @router.patch("/api/image-conversations/{conversation_id}/turns/{turn_id}")
    async def update_image_conversation_turn(
        conversation_id: str,
        turn_id: str,
        body: TurnPatchRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization, request)
        try:
            item = await run_in_threadpool(
                image_conversation_service.update_turn,
                identity,
                conversation_id=conversation_id,
                turn_id=turn_id,
                updates=_patch_dict(body),
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
        return {"item": item}

    @router.patch("/api/image-conversations/{conversation_id}/results/{image_id}")
    async def update_image_conversation_result(
        conversation_id: str,
        image_id: str,
        body: ResultPatchRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization, request)
        try:
            item = await run_in_threadpool(
                image_conversation_service.update_result,
                identity,
                conversation_id=conversation_id,
                image_id=image_id,
                updates=_patch_dict(body),
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc
        return {"item": item}

    @router.delete("/api/image-conversations/{conversation_id}")
    async def delete_image_conversation(
        conversation_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization, request)
        try:
            return await run_in_threadpool(
                image_conversation_service.delete_conversation,
                identity,
                conversation_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)}) from exc

    return router
