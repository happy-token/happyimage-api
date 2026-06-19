from __future__ import annotations

import os
from unittest import mock

from fastapi.testclient import TestClient

from api.app import create_app


def test_password_login_sets_cookie_and_cookie_authenticates_admin_api():
    with mock.patch.dict(
        os.environ,
        {
            "HAPPYIMAGE_AUTH_KEY": "cookie-test-admin-key",
            "HAPPYIMAGE_SESSION_SECRET": "cookie-test-session-secret",
            "HAPPYIMAGE_FRONTEND_BASE_URL": "http://localhost:3000",
        },
        clear=False,
    ):
        with TestClient(create_app()) as client:
            login_response = client.post("/api/auth/login", json={"access_key": "cookie-test-admin-key"})

            assert login_response.status_code == 200, login_response.text
            assert "httponly" in login_response.headers.get("set-cookie", "").lower()

            settings_response = client.get("/api/settings")

            assert settings_response.status_code == 200, settings_response.text
            assert "config" in settings_response.json()

            models_response = client.get("/v1/models")

            assert models_response.status_code == 200, models_response.text


def test_cookie_auth_rejects_untrusted_write_origin():
    with mock.patch.dict(
        os.environ,
        {
            "HAPPYIMAGE_AUTH_KEY": "cookie-test-admin-key",
            "HAPPYIMAGE_SESSION_SECRET": "cookie-test-session-secret",
            "HAPPYIMAGE_FRONTEND_BASE_URL": "http://localhost:3000",
        },
        clear=False,
    ):
        with TestClient(create_app()) as client:
            login_response = client.post("/api/auth/login", json={"access_key": "cookie-test-admin-key"})
            assert login_response.status_code == 200, login_response.text

            response = client.post(
                "/api/settings",
                json={},
                headers={"Origin": "http://evil.example"},
            )

            assert response.status_code == 403, response.text
