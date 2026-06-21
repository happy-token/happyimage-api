from __future__ import annotations

import base64
import os
from unittest import mock

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.testclient import TestClient

import api.ai as ai_api
from api.app import create_app


HAPPYIMAGE_KEY = "happyimage-upstream-key"
NEWAPI_KEY = "newapi-user-key"
PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")


def _make_newapi_gateway(upstream: TestClient) -> TestClient:
    app = FastAPI()

    @app.api_route("/v1/{path:path}", methods=["GET", "POST"])
    async def forward_openai_compatible(path: str, request: Request):
        authorization = request.headers.get("authorization", "")
        if authorization != f"Bearer {NEWAPI_KEY}":
            return Response(status_code=401, content=b'{"error":"invalid newapi token"}', media_type="application/json")
        body = await request.body()
        headers = {"Authorization": f"Bearer {HAPPYIMAGE_KEY}"}
        content_type = request.headers.get("content-type")
        if content_type:
            headers["Content-Type"] = content_type
        upstream_response = upstream.request(
            request.method,
            f"/v1/{path}",
            params=dict(request.query_params),
            headers=headers,
            content=body,
        )
        return Response(
            status_code=upstream_response.status_code,
            content=upstream_response.content,
            media_type=upstream_response.headers.get("content-type", "application/json"),
        )

    return TestClient(app)


def test_newapi_gateway_chain_for_openai_compatible_routes():
    with mock.patch.dict(
        os.environ,
        {
            "HAPPYIMAGE_AUTH_KEY": HAPPYIMAGE_KEY,
            "HAPPYIMAGE_SESSION_SECRET": "newapi-chain-session-secret",
            "HAPPYIMAGE_FRONTEND_BASE_URL": "http://localhost:3000",
        },
        clear=False,
    ), mock.patch.object(
        ai_api.openai_v1_models,
        "list_models",
        return_value={
            "object": "list",
            "data": [
                {"id": "gpt-image-2", "object": "model", "created": 0, "owned_by": "happyimage"},
                {"id": "auto", "object": "model", "created": 0, "owned_by": "happyimage"},
            ],
        },
    ), mock.patch.object(
        ai_api.openai_v1_image_generations,
        "handle",
        return_value={"created": 1, "data": [{"b64_json": "ZmFrZS1pbWFnZQ=="}]},
    ), mock.patch.object(
        ai_api.openai_v1_image_edit,
        "handle",
        return_value={"created": 1, "data": [{"b64_json": "ZmFrZS1lZGl0"}]},
    ), mock.patch.object(
        ai_api.openai_v1_chat_complete,
        "handle",
        return_value={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": "auto",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        },
    ), mock.patch.object(
        ai_api.openai_v1_response,
        "handle",
        return_value={
            "id": "resp-test",
            "object": "response",
            "created_at": 1,
            "status": "completed",
            "model": "auto",
            "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "ok"}]}],
        },
    ), mock.patch.object(ai_api, "check_request", return_value=None):
        upstream = TestClient(create_app())
        newapi = _make_newapi_gateway(upstream)

        headers = {"Authorization": f"Bearer {NEWAPI_KEY}"}
        models = newapi.get("/v1/models", headers=headers)
        assert models.status_code == 200, models.text
        assert [item["id"] for item in models.json()["data"]] == ["gpt-image-2", "auto"]

        generation = newapi.post(
            "/v1/images/generations",
            headers=headers,
            json={"model": "gpt-image-2", "prompt": "cat", "response_format": "b64_json"},
        )
        assert generation.status_code == 200, generation.text
        assert generation.json()["data"][0]["b64_json"] == "ZmFrZS1pbWFnZQ=="

        edit = newapi.post(
            "/v1/images/edits",
            headers=headers,
            json={"model": "gpt-image-2", "prompt": "edit cat", "image": PNG_DATA_URL, "response_format": "b64_json"},
        )
        assert edit.status_code == 200, edit.text
        assert edit.json()["data"][0]["b64_json"] == "ZmFrZS1lZGl0"

        chat = newapi.post(
            "/v1/chat/completions",
            headers=headers,
            json={"model": "auto", "messages": [{"role": "user", "content": "hello"}]},
        )
        assert chat.status_code == 200, chat.text
        assert chat.json()["choices"][0]["message"]["content"] == "ok"

        response = newapi.post(
            "/v1/responses",
            headers=headers,
            json={"model": "auto", "input": "hello"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "completed"


def test_newapi_gateway_does_not_cover_happyimage_web_api_routes():
    upstream = TestClient(create_app())
    newapi = _make_newapi_gateway(upstream)

    response = newapi.get("/api/auth/session", headers={"Authorization": f"Bearer {NEWAPI_KEY}"})

    assert response.status_code == 404
