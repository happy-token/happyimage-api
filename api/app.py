from __future__ import annotations

from contextlib import asynccontextmanager
from threading import Event

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from api import auth_oidc, image_conversations, image_tasks, seed_gallery, share_drafts, system
from api.errors import install_exception_handlers
from api.support import reset_current_request, resolve_web_asset, set_current_request
from services.config import config
from services.image_service import start_image_cleanup_scheduler

WEB_STATIC_CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"
WEB_APP_ASSET_CACHE_CONTROL = "no-cache"


def web_asset_cache_headers(path: str) -> dict[str, str]:
    clean_path = path.strip("/")
    if clean_path.startswith("_next/static/"):
        return {"Cache-Control": WEB_APP_ASSET_CACHE_CONTROL}
    if clean_path.endswith((".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff", ".woff2")):
        return {"Cache-Control": WEB_STATIC_CACHE_CONTROL}
    return {"Cache-Control": "no-cache"}


def create_app() -> FastAPI:
    app_version = config.app_version

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        stop_event = Event()
        cleanup_thread = start_image_cleanup_scheduler(stop_event)
        config.cleanup_old_images()
        try:
            yield
        finally:
            stop_event.set()
            cleanup_thread.join(timeout=1)

    app = FastAPI(title="Happy Token", version=app_version, lifespan=lifespan)
    install_exception_handlers(app)

    @app.middleware("http")
    async def add_security_headers(request, call_next):
        request_token = set_current_request(request)
        try:
            response = await call_next(request)
        finally:
            reset_current_request(request_token)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        if proto == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    # CORS: support credentials for configured frontend origins.
    # Wildcard origins when no specific frontend is configured.
    cors_origins = config.cors_origins
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(auth_oidc.create_router())
    app.include_router(image_conversations.create_router())
    app.include_router(image_tasks.create_router())
    app.include_router(seed_gallery.create_router())
    app.include_router(share_drafts.create_router())
    app.include_router(system.create_router(app_version))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_web(full_path: str):
        asset = resolve_web_asset(full_path)
        if asset is not None:
            return FileResponse(asset, headers=web_asset_cache_headers(full_path))
        clean_path = full_path.strip("/")
        if clean_path.startswith(("_next/", "api/", "v1/")):
            raise HTTPException(status_code=404, detail="Not Found")
        fallback = resolve_web_asset("")
        if fallback is None:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(fallback, headers={"Cache-Control": "no-cache"})

    return app
