from __future__ import annotations

import base64
import os
from unittest import mock

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.testclient import TestClient

import api.ai as ai_api
from api.app import create_app


HAPPYTOKEN_KEY = "happytoken-upstream-key"
NEWAPI_KEY = "newapi-user-key"
PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
GATEWAY_IDENTITY = {
    "id": "user-1",
    "name": "User",
    "role": "user",
    "model_provider": "newapi",
    "model_base_url": "https://gateway.example.test/v1",
    "model_api_key": "sk-user-provider",
}


def _make_newapi_gateway(upstream: TestClient) -> TestClient:
    app = FastAPI()

    @app.api_route("/v1/{path:path}", methods=["GET", "POST"])
    async def forward_openai_compatible(path: str, request: Request):
        authorization = request.headers.get("authorization", "")
        if authorization != f"Bearer {NEWAPI_KEY}":
            return Response(status_code=401, content=b'{"error":"invalid newapi token"}', media_type="application/json")
        body = await request.body()
        headers = {"Authorization": f"Bearer {HAPPYTOKEN_KEY}"}
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


def test_newapi_gateway_chain_for_image_compatible_routes():
    with mock.patch.dict(
        os.environ,
        {
            "HAPPYTOKEN_SESSION_SECRET": "newapi-chain-session-secret",
            "HAPPYTOKEN_FRONTEND_BASE_URL": "http://localhost:3000",
        },
        clear=False,
    ), mock.patch.object(
        ai_api.openai_v1_models,
        "list_models",
        return_value={
            "object": "list",
            "data": [
                {"id": "gpt-image-2", "object": "model", "created": 0, "owned_by": "happytoken"},
                {"id": "auto", "object": "model", "created": 0, "owned_by": "happytoken"},
            ],
        },
    ), mock.patch.object(
        ai_api.model_gateway_service,
        "generate_image",
        return_value={"created": 1, "data": [{"b64_json": "ZmFrZS1pbWFnZQ=="}]},
    ), mock.patch.object(
        ai_api.model_gateway_service,
        "edit_image",
        return_value={"created": 1, "data": [{"b64_json": "ZmFrZS1lZGl0"}]},
    ), mock.patch.object(ai_api, "check_request", return_value=None), mock.patch.object(
        ai_api,
        "require_identity",
        return_value=GATEWAY_IDENTITY,
    ):
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


def test_newapi_gateway_does_not_cover_happytoken_web_api_routes():
    upstream = TestClient(create_app())
    newapi = _make_newapi_gateway(upstream)

    response = newapi.get("/api/auth/session", headers={"Authorization": f"Bearer {NEWAPI_KEY}"})

    assert response.status_code == 404
