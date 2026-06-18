from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from services.seed_gallery_service import seed_gallery_service

SEED_GALLERY_LIST_CACHE_CONTROL = "public, max-age=300, stale-while-revalidate=3600"
SEED_GALLERY_DETAIL_CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"
SEED_GALLERY_IMAGE_CACHE_CONTROL = "public, max-age=31536000, immutable"


def set_cache_header(response: Response, value: str) -> None:
    response.headers["Cache-Control"] = value


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/seed-gallery")
    async def list_seed_gallery(
        response: Response,
        query: str = "",
        category: str = "",
        watermark_status: str = "",
        limit: int = Query(default=60, ge=1, le=240),
        offset: int = Query(default=0, ge=0),
    ):
        set_cache_header(response, SEED_GALLERY_LIST_CACHE_CONTROL)
        return await run_in_threadpool(
            seed_gallery_service.list_items,
            query=query,
            category=category,
            watermark_status=watermark_status,
            limit=limit,
            offset=offset,
        )

    @router.get("/api/seed-gallery/facets")
    async def get_seed_gallery_facets(response: Response):
        set_cache_header(response, SEED_GALLERY_DETAIL_CACHE_CONTROL)
        return await run_in_threadpool(seed_gallery_service.facets)

    @router.get("/api/seed-gallery/images/{image_path:path}", include_in_schema=False)
    async def get_seed_gallery_image(image_path: str):
        resolved = await run_in_threadpool(seed_gallery_service.resolve_image_path, image_path)
        if resolved is None:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(resolved, headers={"Cache-Control": SEED_GALLERY_IMAGE_CACHE_CONTROL})

    @router.get("/api/seed-gallery/thumbnails/{width}/{image_path:path}", include_in_schema=False)
    async def get_seed_gallery_thumbnail(width: int, image_path: str):
        resolved = await run_in_threadpool(seed_gallery_service.resolve_thumbnail_path, width, image_path)
        if resolved is None:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(resolved, headers={"Cache-Control": SEED_GALLERY_IMAGE_CACHE_CONTROL})

    @router.get("/api/seed-gallery/{case_id}/related")
    async def get_related_seed_gallery_cases(
        response: Response,
        case_id: str,
        limit: int = Query(default=4, ge=1, le=12),
    ):
        set_cache_header(response, SEED_GALLERY_DETAIL_CACHE_CONTROL)
        return await run_in_threadpool(seed_gallery_service.related_items, case_id, limit=limit)

    @router.get("/api/seed-gallery/{case_id}")
    async def get_seed_gallery_case(response: Response, case_id: str):
        item = await run_in_threadpool(seed_gallery_service.get_item, case_id)
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "图库素材不存在"})
        set_cache_header(response, SEED_GALLERY_DETAIL_CACHE_CONTROL)
        return {"item": item}

    return router
