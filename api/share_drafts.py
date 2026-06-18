from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from api.support import require_identity
from services.gallery_prompt_service import generate_conversation_summary, generate_share_prompt
from services.share_draft_service import share_draft_service


class GalleryConversationMessage(BaseModel):
    role: str = Field(default="", max_length=32)
    content: str = Field(default="", max_length=4000)


class GalleryTextRequest(BaseModel):
    conversation_id: str = Field(..., min_length=1, max_length=100)
    conversation_title: str = Field(default="", max_length=200)
    original_prompt: str = Field(..., min_length=1, max_length=8000)
    image_url: str = Field(..., min_length=1, max_length=2048)
    model: str = Field(default="", max_length=100)
    size: str = Field(default="", max_length=50)
    quality: str = Field(default="", max_length=50)
    conversation_summary: str = Field(default="", max_length=4000)
    conversation_messages: list[GalleryConversationMessage] = Field(default_factory=list, max_length=40)


ShareDraftTag = Annotated[str, Field(max_length=50)]


class ShareDraftRequest(BaseModel):
    id: str | None = Field(default=None, max_length=100)
    source: str = Field(default="user_gallery", min_length=1, max_length=50)
    image_url: str = Field(..., min_length=1, max_length=2048)
    conversation_id: str = Field(..., min_length=1, max_length=100)
    turn_id: str = Field(..., min_length=1, max_length=100)
    image_id: str = Field(..., min_length=1, max_length=100)
    original_prompt: str = Field(..., min_length=1, max_length=8000)
    conversation_summary: str = Field(default="", max_length=4000)
    share_prompt: str = Field(..., min_length=1, max_length=8000)
    title: str = Field(..., min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    tags: list[ShareDraftTag] = Field(default_factory=list, max_length=20)
    status: str = Field(default="draft", min_length=1, max_length=50)


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/user-gallery/summarize")
    async def summarize_gallery_item(
        body: GalleryTextRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        require_identity(authorization)
        summary = await run_in_threadpool(generate_conversation_summary, body.model_dump())
        return {"summary": summary}

    @router.post("/api/user-gallery/generate-share-prompt")
    async def generate_gallery_share_prompt(
        body: GalleryTextRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        require_identity(authorization)
        share_prompt = await run_in_threadpool(generate_share_prompt, body.model_dump())
        return {"share_prompt": share_prompt}

    @router.get("/api/share-drafts")
    async def list_share_drafts(
        authorization: str | None = Header(default=None),
    ) -> dict[str, list[dict[str, Any]]]:
        identity = require_identity(authorization)
        return await run_in_threadpool(share_draft_service.list_drafts, identity)

    @router.post("/api/share-drafts")
    async def save_share_draft(
        body: ShareDraftRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        identity = require_identity(authorization)
        try:
            item = await run_in_threadpool(share_draft_service.save_draft, identity, body.model_dump())
            return {"item": item}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    return router
