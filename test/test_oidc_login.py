from __future__ import annotations

import os
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.auth_oidc as auth_oidc_api
from services.oidc_service import OIDCService
from services.web_session_service import web_session_service


def test_oidc_authorize_and_callback_reuse_absolute_redirect_uri():
    service = OIDCService()
    with mock.patch.dict(
        os.environ,
        {
            "HAPPYTOKEN_OIDC_ENABLED": "true",
            "HAPPYTOKEN_OIDC_ISSUER": "https://issuer.example",
            "HAPPYTOKEN_OIDC_CLIENT_ID": "happytoken",
            "HAPPYTOKEN_OIDC_CLIENT_SECRET": "secret",
        },
        clear=False,
    ), mock.patch.object(
        service,
        "_fetch_discovery",
        return_value={
            "authorization_endpoint": "https://issuer.example/authorize",
            "token_endpoint": "https://issuer.example/token",
            "userinfo_endpoint": "https://issuer.example/userinfo",
        },
    ), mock.patch.object(service, "_fetch_userinfo", return_value={"email": "creator@example.com"}):
        start = service.build_authorize_url(
            next_path="/image",
            api_base_url="https://api.example.com",
        )
        query = parse_qs(urlsplit(start["authorize_url"]).query)
        state = query["state"][0]
        assert query["redirect_uri"] == ["https://api.example.com/api/auth/oidc/callback"]

        captured = {}

        def exchange(**kwargs):
            captured.update(kwargs)
            return {"access_token": "access", "id_token": "header.payload.sig"}

        with mock.patch.object(service, "_exchange_code", side_effect=exchange), mock.patch.object(
            service,
            "_validate_id_token_claims",
            return_value={"sub": "oidc-sub", "nonce": "unused"},
        ):
            claims = service.handle_callback(code="code", state=state)

        assert captured["redirect_uri"] == "https://api.example.com/api/auth/oidc/callback"
        assert claims["sub"] == "oidc-sub"
        assert claims["email"] == "creator@example.com"


def test_oidc_callback_session_cookie_contains_external_identity():
    app = FastAPI()
    app.include_router(auth_oidc_api.create_router())

    user_item = {
        "id": "user-oidc",
        "name": "Creator",
        "role": "user",
        "enabled": True,
        "auth_provider": "oidc",
        "auth_subject": "subject-1",
        "email": "creator@example.com",
    }

    with mock.patch.dict(
        os.environ,
        {
            "HAPPYTOKEN_SESSION_SECRET": "oidc-session-secret",
            "HAPPYTOKEN_OIDC_ENABLED": "true",
            "HAPPYTOKEN_FRONTEND_BASE_URL": "https://web.example.com",
        },
        clear=False,
    ), mock.patch.object(
        auth_oidc_api.oidc_service,
        "handle_callback",
        return_value={"sub": "subject-1", "email": "creator@example.com", "name": "Creator", "next_path": "/image"},
    ), mock.patch.object(
        auth_oidc_api.auth_service,
        "find_or_create_oidc_user",
        return_value=user_item,
    ):
        client = TestClient(app)
        response = client.get("/api/auth/oidc/callback?code=code&state=state", follow_redirects=False)

        assert response.status_code == 302, response.text
        cookie = response.headers["set-cookie"]
        token = cookie.split("happytoken_session=", 1)[1].split(";", 1)[0]
        payload = web_session_service.verify_session(token)

        assert response.headers["location"] == "https://web.example.com/image"
        assert payload["auth_provider"] == "oidc"
        assert payload["auth_subject"] == "subject-1"
        assert payload["email"] == "creator@example.com"


def test_logout_clear_cookie_matches_cross_site_secure_cookie_attributes():
    app = FastAPI()
    app.include_router(auth_oidc_api.create_router())

    with mock.patch.dict(
        os.environ,
        {
            "HAPPYTOKEN_API_BASE_URL": "https://api.example.com",
            "HAPPYTOKEN_FRONTEND_BASE_URL": "https://web.example.com",
            "HAPPYTOKEN_SESSION_SECRET": "oidc-session-secret",
        },
        clear=False,
    ):
        response = TestClient(app).post("/api/auth/logout")

    assert response.status_code == 200, response.text
    cookie = response.headers["set-cookie"]
    assert "happytoken_session=" in cookie
    assert "Max-Age=0" in cookie
    assert "Expires=Thu, 01 Jan 1970 00:00:00 GMT" in cookie
    assert "Secure" in cookie
    assert "SameSite=None" in cookie
