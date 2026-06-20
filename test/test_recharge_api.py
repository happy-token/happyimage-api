from __future__ import annotations

import os
import uuid
from unittest import mock

from fastapi.testclient import TestClient

from api.app import create_app
from services.auth_service import auth_service
from services.web_session_service import web_session_service


def test_recharge_session_returns_newapi_redirect_url():
    with mock.patch.dict(
        os.environ,
        {
            "HAPPYIMAGE_AUTH_KEY": "recharge-session-admin-key",
            "HAPPYIMAGE_SESSION_SECRET": "recharge-session-secret",
            "HAPPYIMAGE_FRONTEND_BASE_URL": "http://localhost:3000",
            "HAPPYIMAGE_RECHARGE_ENABLED": "true",
            "HAPPYIMAGE_RECHARGE_PROVIDER": "newapi",
            "HAPPYIMAGE_NEWAPI_BASE_URL": "https://new-api.example.com",
        },
        clear=False,
    ):
        with TestClient(create_app()) as client:
            assert client.post("/api/auth/login", json={"access_key": "recharge-session-admin-key"}).status_code == 200
            user_key = f"recharge-user-key-{uuid.uuid4().hex}"
            create_response = client.post(
                "/api/auth/users",
                json={"name": f"recharge-user-{uuid.uuid4().hex[:8]}", "key": user_key, "image_quota": 12},
            )
            assert create_response.status_code == 200, create_response.text

            assert client.post("/api/auth/login", json={"access_key": user_key}).status_code == 200
            response = client.get("/api/recharge/session")

            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["provider"] == "newapi"
            assert payload["mode"] == "redirect"
            assert payload["quota"] == 12
            assert payload["recharge_url"].startswith("https://new-api.example.com/console/topup?")
            assert "source=happyimage" in payload["recharge_url"]
            assert "return_url=http%3A%2F%2Flocalhost%3A3000%2Fimage" in payload["recharge_url"]


def test_newapi_recharge_webhook_adds_user_quota():
    with mock.patch.dict(
        os.environ,
        {
            "HAPPYIMAGE_AUTH_KEY": "recharge-webhook-admin-key",
            "HAPPYIMAGE_SESSION_SECRET": "recharge-webhook-secret",
            "HAPPYIMAGE_RECHARGE_WEBHOOK_SECRET": "newapi-callback-secret",
        },
        clear=False,
    ):
        with TestClient(create_app()) as client:
            assert client.post("/api/auth/login", json={"access_key": "recharge-webhook-admin-key"}).status_code == 200
            create_response = client.post(
                "/api/auth/users",
                json={"name": f"webhook-user-{uuid.uuid4().hex[:8]}", "image_quota": 3},
            )
            assert create_response.status_code == 200, create_response.text
            user_id = create_response.json()["item"]["id"]

            webhook_response = client.post(
                "/api/recharge/newapi/webhook",
                headers={"X-HappyImage-Recharge-Secret": "newapi-callback-secret"},
                json={
                    "status": "paid",
                    "order_id": f"order-{uuid.uuid4().hex}",
                    "happyimage_user_id": user_id,
                    "quota": 7,
                },
            )

            assert webhook_response.status_code == 200, webhook_response.text
            payload = webhook_response.json()
            assert payload["ok"] is True
            assert payload["user_id"] == user_id
            assert payload["image_quota"] == 10


def test_recharge_session_includes_oidc_identity_in_newapi_url():
    subject = f"casdoor-sub-{uuid.uuid4().hex}"
    email = f"casdoor-{uuid.uuid4().hex[:8]}@example.com"
    with mock.patch.dict(
        os.environ,
        {
            "HAPPYIMAGE_AUTH_KEY": "recharge-oidc-admin-key",
            "HAPPYIMAGE_SESSION_SECRET": "recharge-oidc-session-secret",
            "HAPPYIMAGE_FRONTEND_BASE_URL": "http://localhost:3000",
            "HAPPYIMAGE_RECHARGE_ENABLED": "true",
            "HAPPYIMAGE_RECHARGE_PROVIDER": "newapi",
            "HAPPYIMAGE_NEWAPI_BASE_URL": "https://new-api.example.com",
        },
        clear=False,
    ):
        user = auth_service.find_or_create_oidc_user(
            auth_provider="oidc",
            auth_subject=subject,
            email=email,
            name=f"Casdoor User {uuid.uuid4().hex[:8]}",
            default_image_quota=9,
        )
        session_token, _cookie = web_session_service.create_session(user)
        with TestClient(create_app()) as client:
            client.cookies.set(web_session_service.cookie_name, session_token)
            response = client.get("/api/recharge/session")

            assert response.status_code == 200, response.text
            url = response.json()["recharge_url"]
            assert f"external_subject={subject}" in url
            assert f"email={email.replace('@', '%40')}" in url
