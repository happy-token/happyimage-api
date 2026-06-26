from __future__ import annotations

from contextlib import contextmanager
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

import api.auth_oidc as auth_oidc_api
from services.config import config
from services.oidc_service import OIDCService
from services.web_session_service import web_session_service


def _oidc_settings(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "enabled": True,
        "issuer": "https://issuer.example",
        "client_id": "happytoken",
        "client_secret": "secret",
    }
    values.update(overrides)
    return values


@contextmanager
def _runtime_config(**overrides: object):
    values: dict[str, object] = {
        "session_secret": "oidc-session-secret",
        "public_app_url": "https://web.example.com",
        "oidc": _oidc_settings(),
    }
    values.update(overrides)
    previous_data = dict(config.data)
    with mock.patch.object(config, "_save"):
        config.data = {}
        config.update(values)
        try:
            yield
        finally:
            config.data = previous_data


def _request(
    *,
    scheme: str = "http",
    host: str = "request.example.com",
    forwarded_proto: str = "",
    forwarded_host: str = "",
) -> Request:
    headers = [(b"host", host.encode("ascii"))]
    if forwarded_proto:
        headers.append((b"x-forwarded-proto", forwarded_proto.encode("ascii")))
    if forwarded_host:
        headers.append((b"x-forwarded-host", forwarded_host.encode("ascii")))
    return Request(
        {
            "type": "http",
            "scheme": scheme,
            "server": (host.split(":", 1)[0], 80),
            "path": "/api/auth/oidc/start",
            "headers": headers,
        }
    )


def test_oidc_authorize_and_callback_reuse_absolute_redirect_uri():
    service = OIDCService()
    with (
        mock.patch.dict(config.data, {"oidc": _oidc_settings()}, clear=False),
        mock.patch.object(
            service,
            "_fetch_discovery",
            return_value={
                "authorization_endpoint": "https://issuer.example/authorize",
                "token_endpoint": "https://issuer.example/token",
                "userinfo_endpoint": "https://issuer.example/userinfo",
            },
        ),
        mock.patch.object(
            service, "_fetch_userinfo", return_value={"email": "creator@example.com"}
        ),
    ):
        start = service.build_authorize_url(
            next_path="/image",
            api_base_url="https://api.example.com",
        )
        query = parse_qs(urlsplit(start["authorize_url"]).query)
        state = query["state"][0]
        assert query["redirect_uri"] == [
            "https://api.example.com/api/auth/oidc/callback"
        ]

        captured = {}

        def exchange(**kwargs):
            captured.update(kwargs)
            return {"access_token": "access", "id_token": "header.payload.sig"}

        with (
            mock.patch.object(service, "_exchange_code", side_effect=exchange),
            mock.patch.object(
                service,
                "_validate_id_token_claims",
                return_value={"sub": "oidc-sub", "nonce": "unused"},
            ),
        ):
            claims = service.handle_callback(code="code", state=state)

        assert (
            captured["redirect_uri"] == "https://api.example.com/api/auth/oidc/callback"
        )
        assert claims["sub"] == "oidc-sub"
        assert claims["email"] == "creator@example.com"


def test_oidc_callback_base_url_prefers_external_api_url_runtime_setting():
    with _runtime_config(
        public_app_url="https://web.example.com",
        api_public_url="https://api.config.example.com",
    ):
        assert (
            auth_oidc_api._request_external_base_url(
                _request(
                    scheme="http",
                    host="internal.example.com",
                    forwarded_proto="https",
                    forwarded_host="proxy.example.com",
                )
            )
            == "https://api.config.example.com"
        )
        assert (
            OIDCService._make_callback_url()
            == "https://api.config.example.com/api/auth/oidc/callback"
        )


def test_oidc_callback_base_url_falls_back_to_forwarded_request_host():
    with _runtime_config(public_app_url="", api_public_url=""):
        assert (
            auth_oidc_api._request_external_base_url(
                _request(
                    scheme="http",
                    host="internal.example.com",
                    forwarded_proto="https",
                    forwarded_host="proxy.example.com",
                )
            )
            == "https://proxy.example.com"
        )


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

    with (
        _runtime_config(),
        mock.patch.object(
            auth_oidc_api.oidc_service,
            "handle_callback",
            return_value={
                "sub": "subject-1",
                "email": "creator@example.com",
                "name": "Creator",
                "next_path": "/image",
            },
        ),
        mock.patch.object(
            auth_oidc_api.auth_service,
            "find_or_create_oidc_user",
            return_value=user_item,
        ),
    ):
        client = TestClient(app)
        response = client.get(
            "/api/auth/oidc/callback?code=code&state=state", follow_redirects=False
        )

        assert response.status_code == 302, response.text
        cookie = response.headers["set-cookie"]
        token = cookie.split("happytoken_session=", 1)[1].split(";", 1)[0]
        payload = web_session_service.verify_session(token)

        assert response.headers["location"] == "https://web.example.com/image"
        assert payload["auth_provider"] == "oidc"
        assert payload["auth_subject"] == "subject-1"
        assert payload["email"] == "creator@example.com"


def test_oidc_callback_applies_newapi_default_provider_when_binding_succeeds():
    app = FastAPI()
    app.include_router(auth_oidc_api.create_router())

    user_item = {
        "id": "user-oidc",
        "name": "Creator",
        "role": "user",
        "enabled": True,
        "auth_provider": "casdoor",
        "auth_subject": "subject-1",
        "email": "creator@example.com",
    }
    updated_item = {
        **user_item,
        "model_provider": "newapi",
        "model_base_url": "https://gateway.happy-token.cn",
        "model_api_key_configured": True,
        "model_providers": [
            {
                "id": "newapi-default",
                "type": "newapi",
                "base_url": "https://gateway.happy-token.cn",
                "api_key_configured": True,
                "selected": True,
            }
        ],
    }

    with (
        _runtime_config(),
        mock.patch.object(
            auth_oidc_api.oidc_service,
            "handle_callback",
            return_value={
                "sub": "subject-1",
                "email": "creator@example.com",
                "name": "Creator",
                "next_path": "/image",
            },
        ),
        mock.patch.object(
            auth_oidc_api.auth_service,
            "find_or_create_oidc_user",
            return_value=user_item,
        ),
        mock.patch.object(
            auth_oidc_api.newapi_binding_service,
            "ensure_default_token",
            return_value={
                "ok": True,
                "status": "configured",
                "base_url": "https://gateway.happy-token.cn",
                "management_url": "https://gateway.happy-token.cn",
                "token": "sk-user-token",
            },
        ) as ensure_token,
        mock.patch.object(
            auth_oidc_api.auth_service,
            "apply_newapi_default_provider",
            return_value=updated_item,
        ) as apply_provider,
    ):
        response = TestClient(app).get(
            "/api/auth/oidc/callback?code=code&state=state", follow_redirects=False
        )

        assert response.status_code == 302, response.text
        ensure_token.assert_called_once_with(
            provider="casdoor",
            subject="subject-1",
            email="creator@example.com",
            name="Creator",
        )
        apply_provider.assert_called_once_with(
            "user-oidc",
            base_url="https://gateway.happy-token.cn",
            api_key="sk-user-token",
        )
        cookie = response.headers["set-cookie"]
        token = cookie.split("happytoken_session=", 1)[1].split(";", 1)[0]
        payload = web_session_service.verify_session(token)
        assert payload["model_provider"] == "newapi"
        assert payload["model_base_url"] == "https://gateway.happy-token.cn"
        assert payload["model_api_key_configured"] is True
        assert payload["model_providers"] == [
            {
                "id": "newapi-default",
                "type": "newapi",
                "base_url": "https://gateway.happy-token.cn",
                "api_key_configured": True,
                "selected": True,
            }
        ]
        assert payload["newapi_binding_status"] == "configured"
        assert payload["newapi_management_url"] == "https://gateway.happy-token.cn"
        assert "sk-user-token" not in str(payload)
        assert "model_api_key" not in payload


def test_oidc_callback_allows_login_when_newapi_binding_is_pending():
    app = FastAPI()
    app.include_router(auth_oidc_api.create_router())

    user_item = {
        "id": "user-oidc-pending",
        "name": "Creator",
        "role": "user",
        "enabled": True,
        "auth_provider": "casdoor",
        "auth_subject": "subject-2",
        "email": "creator2@example.com",
    }

    with (
        _runtime_config(),
        mock.patch.object(
            auth_oidc_api.oidc_service,
            "handle_callback",
            return_value={
                "sub": "subject-2",
                "email": "creator2@example.com",
                "name": "Creator",
                "next_path": "/image",
            },
        ),
        mock.patch.object(
            auth_oidc_api.auth_service,
            "find_or_create_oidc_user",
            return_value=user_item,
        ),
        mock.patch.object(
            auth_oidc_api.newapi_binding_service,
            "ensure_default_token",
            return_value={
                "ok": False,
                "status": "pending",
                "message": "NewAPI provisioning endpoint is not configured",
                "base_url": "https://gateway.happy-token.cn",
                "management_url": "https://gateway.happy-token.cn",
            },
        ) as ensure_token,
        mock.patch.object(
            auth_oidc_api.auth_service,
            "apply_newapi_default_provider",
        ) as apply_provider,
    ):
        response = TestClient(app).get(
            "/api/auth/oidc/callback?code=code&state=state", follow_redirects=False
        )

        assert response.status_code == 302, response.text
        ensure_token.assert_called_once_with(
            provider="casdoor",
            subject="subject-2",
            email="creator2@example.com",
            name="Creator",
        )
        apply_provider.assert_not_called()
        cookie = response.headers["set-cookie"]
        token = cookie.split("happytoken_session=", 1)[1].split(";", 1)[0]
        payload = web_session_service.verify_session(token)
        assert payload["newapi_binding_status"] == "pending"
        assert (
            payload["newapi_binding_message"]
            == "NewAPI provisioning endpoint is not configured"
        )


def test_oidc_callback_allows_login_when_newapi_provider_apply_fails():
    app = FastAPI()
    app.include_router(auth_oidc_api.create_router())

    user_item = {
        "id": "user-oidc-failed",
        "name": "Creator",
        "role": "user",
        "enabled": True,
        "auth_provider": "casdoor",
        "auth_subject": "subject-failed",
        "email": "creator-failed@example.com",
    }

    with (
        _runtime_config(),
        mock.patch.object(
            auth_oidc_api.oidc_service,
            "handle_callback",
            return_value={
                "sub": "subject-failed",
                "email": "creator-failed@example.com",
                "name": "Creator",
                "next_path": "/image",
            },
        ),
        mock.patch.object(
            auth_oidc_api.auth_service,
            "find_or_create_oidc_user",
            return_value=user_item,
        ),
        mock.patch.object(
            auth_oidc_api.newapi_binding_service,
            "ensure_default_token",
            return_value={
                "ok": True,
                "status": "configured",
                "base_url": "",
                "management_url": "https://gateway.happy-token.cn",
                "token": "sk-user-token",
            },
        ),
        mock.patch.object(
            auth_oidc_api.auth_service,
            "apply_newapi_default_provider",
            side_effect=ValueError("NewAPI 默认供应商配置不完整"),
        ),
    ):
        response = TestClient(app).get(
            "/api/auth/oidc/callback?code=code&state=state", follow_redirects=False
        )

        assert response.status_code == 302, response.text
        cookie = response.headers["set-cookie"]
        token = cookie.split("happytoken_session=", 1)[1].split(";", 1)[0]
        payload = web_session_service.verify_session(token)
    assert payload["newapi_binding_status"] == "failed"
    assert payload["newapi_binding_message"] == "NewAPI 默认供应商配置不完整"
    assert "sk-user-token" not in str(payload)


def test_get_session_retries_pending_newapi_binding_from_session_identity():
    app = FastAPI()
    app.include_router(auth_oidc_api.create_router())

    user_item = {
        "id": "user-oidc-session",
        "name": "Creator",
        "role": "user",
        "enabled": True,
        "auth_provider": "casdoor",
        "auth_subject": "subject-session",
        "email": "creator@example.com",
    }

    with (
        mock.patch.object(
            auth_oidc_api,
            "resolve_identity_for_request",
            return_value={
                "id": "user-oidc-session",
                "name": "Creator",
                "role": "user",
                "newapi_binding_status": "pending",
                "newapi_binding_message": "NewAPI provisioning endpoint is not configured",
                "newapi_management_url": "https://gateway.happy-token.cn",
            },
        ),
        mock.patch.object(
            auth_oidc_api.auth_service,
            "get_key",
            return_value=user_item,
        ),
        mock.patch.object(
            auth_oidc_api.newapi_binding_service,
            "ensure_default_token",
            return_value={
                "ok": True,
                "status": "configured",
                "token": "sk-recovered",
                "base_url": "https://gateway.happy-token.cn/v1",
                "management_url": "https://gateway.happy-token.cn",
            },
        ) as ensure_token,
        mock.patch.object(
            auth_oidc_api.auth_service,
            "apply_newapi_default_provider",
            return_value={
                **user_item,
                "model_provider": "newapi",
                "model_base_url": "https://gateway.happy-token.cn/v1",
                "model_api_key_configured": True,
            },
        ) as apply_provider,
    ):
        response = TestClient(app).get("/api/auth/session")

    assert response.status_code == 200, response.text
    payload = response.json()
    ensure_token.assert_called_once_with(
        provider="casdoor",
        subject="subject-session",
        email="creator@example.com",
        name="Creator",
    )
    apply_provider.assert_called_once_with(
        "user-oidc-session",
        base_url="https://gateway.happy-token.cn/v1",
        api_key="sk-recovered",
    )
    assert payload["newapi_binding_status"] == "configured"
    assert payload["newapi_management_url"] == "https://gateway.happy-token.cn"
    assert payload["user"]["newapi_binding_status"] == "configured"
    assert payload["user"]["newapi_management_url"] == "https://gateway.happy-token.cn"


def test_get_session_ignores_newapi_cookie_fields_from_different_user():
    app = FastAPI()
    app.include_router(auth_oidc_api.create_router())

    user_item = {
        "id": "bearer-user",
        "name": "Bearer Creator",
        "role": "user",
        "enabled": True,
    }

    with _runtime_config(oidc={}):
        stale_token = web_session_service.sign_session(
            {
                "sub": "cookie-user",
                "name": "Cookie Creator",
                "role": "user",
                "iat": 1,
                "exp": 9999999999,
                "newapi_binding_status": "pending",
                "newapi_binding_message": "stale cookie status",
                "newapi_management_url": "https://stale.example.com",
            }
        )
        with (
            mock.patch.object(
                auth_oidc_api,
                "resolve_identity_for_request",
                return_value={
                    "id": "bearer-user",
                    "name": "Bearer Creator",
                    "role": "user",
                },
            ),
            mock.patch.object(
                auth_oidc_api.auth_service,
                "get_key",
                return_value=user_item,
            ),
        ):
            client = TestClient(app)
            client.cookies.set(web_session_service.cookie_name, stale_token)
            response = client.get(
                "/api/auth/session", headers={"Authorization": "Bearer bearer-token"}
            )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "newapi_binding_status" not in payload
    assert "newapi_binding_message" not in payload
    assert "newapi_management_url" not in payload
    assert "newapi_binding_status" not in payload["user"]


def test_logout_clear_cookie_matches_cross_site_secure_cookie_attributes():
    app = FastAPI()
    app.include_router(auth_oidc_api.create_router())

    with _runtime_config(api_public_url="https://api.example.com"):
        response = TestClient(app).post("/api/auth/logout")

    assert response.status_code == 200, response.text
    cookie = response.headers["set-cookie"]
    assert "happytoken_session=" in cookie
    assert "Max-Age=0" in cookie
    assert "Expires=Thu, 01 Jan 1970 00:00:00 GMT" in cookie
    assert "Secure" in cookie
    assert "SameSite=None" in cookie


def test_logout_clear_cookie_is_secure_when_public_app_url_is_https():
    app = FastAPI()
    app.include_router(auth_oidc_api.create_router())

    with _runtime_config(api_public_url="", public_app_url="https://web.example.com"):
        response = TestClient(app).post("/api/auth/logout")

    assert response.status_code == 200, response.text
    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie
    assert "SameSite=None" in cookie


def test_logout_clear_cookie_uses_lax_for_http_test_origin():
    app = FastAPI()
    app.include_router(auth_oidc_api.create_router())

    with _runtime_config(
        api_public_url="http://101.96.195.224",
        public_app_url="http://101.96.195.224:3000",
    ):
        response = TestClient(app).post("/api/auth/logout")

    assert response.status_code == 200, response.text
    cookie = response.headers["set-cookie"]
    assert "happytoken_session=" in cookie
    assert "Max-Age=0" in cookie
    assert "Secure" not in cookie
    assert "SameSite=Lax" in cookie
