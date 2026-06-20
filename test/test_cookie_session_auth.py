from __future__ import annotations

import os
import uuid
from unittest import mock

from fastapi.testclient import TestClient

from api.app import create_app
from services.config import config


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


def test_session_accepts_bearer_token_when_cookie_is_missing():
    with mock.patch.dict(
        os.environ,
        {
            "HAPPYIMAGE_AUTH_KEY": "bearer-session-admin-key",
            "HAPPYIMAGE_SESSION_SECRET": "cookie-test-session-secret",
            "HAPPYIMAGE_FRONTEND_BASE_URL": "http://localhost:3000",
        },
        clear=False,
    ):
        with TestClient(create_app()) as client:
            response = client.get(
                "/api/auth/session",
                headers={"Authorization": "Bearer bearer-session-admin-key"},
            )

            assert response.status_code == 200, response.text
            assert response.json()["role"] == "admin"


def test_admin_created_user_gets_default_quota_and_recharge_unlocks_watermark():
    with mock.patch.dict(
        os.environ,
        {
            "HAPPYIMAGE_AUTH_KEY": "default-quota-admin-key",
            "HAPPYIMAGE_SESSION_SECRET": "cookie-test-session-secret",
            "HAPPYIMAGE_FRONTEND_BASE_URL": "http://localhost:3000",
            "HAPPYIMAGE_DEFAULT_USER_IMAGE_QUOTA": "20",
        },
        clear=False,
    ):
        with TestClient(create_app()) as client:
            login_response = client.post("/api/auth/login", json={"access_key": "default-quota-admin-key"})
            assert login_response.status_code == 200, login_response.text

            user_name = f"user-{uuid.uuid4().hex[:8]}"
            create_response = client.post("/api/auth/users", json={"name": user_name})
            assert create_response.status_code == 200, create_response.text
            item = create_response.json()["item"]
            assert item["image_quota"] == 20
            assert item["watermark_unlocked"] is False

            update_response = client.post(
                f"/api/auth/users/{item['id']}",
                json={"image_quota": 25},
            )
            assert update_response.status_code == 200, update_response.text
            assert update_response.json()["item"]["watermark_unlocked"] is True


def test_user_profile_can_update_watermark_label():
    with mock.patch.dict(
        os.environ,
        {
            "HAPPYIMAGE_AUTH_KEY": "profile-admin-key",
            "HAPPYIMAGE_SESSION_SECRET": "cookie-test-session-secret",
            "HAPPYIMAGE_FRONTEND_BASE_URL": "http://localhost:3000",
        },
        clear=False,
    ):
        with TestClient(create_app()) as client:
            login_response = client.post("/api/auth/login", json={"access_key": "profile-admin-key"})
            assert login_response.status_code == 200, login_response.text

            user_name = f"profile-{uuid.uuid4().hex[:8]}"
            user_key = f"profile-key-{uuid.uuid4().hex}"
            create_response = client.post("/api/auth/users", json={"name": user_name, "key": user_key})
            assert create_response.status_code == 200, create_response.text

            user_login_response = client.post("/api/auth/login", json={"access_key": user_key})
            assert user_login_response.status_code == 200, user_login_response.text

            update_response = client.patch("/api/auth/profile", json={"watermark_label": "Happy Creator"})
            assert update_response.status_code == 200, update_response.text
            payload = update_response.json()
            assert payload["user"]["watermark_label"] == "Happy Creator"
            assert payload["user"]["watermark_unlocked"] is False


def test_test_user_password_login_is_case_insensitive():
    with mock.patch.dict(
        os.environ,
        {
            "HAPPYIMAGE_AUTH_KEY": "cookie-test-admin-key",
            "HAPPYIMAGE_SESSION_SECRET": "cookie-test-session-secret",
            "HAPPYIMAGE_FRONTEND_BASE_URL": "http://localhost:3000",
            "HAPPYIMAGE_TEST_ACCOUNTS_ENABLED": "true",
        },
        clear=False,
    ):
        fake_identity = {"id": "user", "name": "user", "role": "user", "image_quota": 10}
        with mock.patch("api.support.auth_service.authenticate", return_value=fake_identity):
            with TestClient(create_app()) as client:
                response = client.post("/api/auth/login", json={"email": "User", "password": "User"})

                assert response.status_code == 200, response.text
                assert response.json()["role"] == "user"


def test_local_image_accepts_bearer_token_when_signed_link_is_missing(tmp_path):
    image_rel = "2026/06/20/test-image.png"
    image_path = config.images_dir / image_rel
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff"
        b"\xff?\x00\x05\xfe\x02\xfeA\xe2!\xbc\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    try:
        with mock.patch.dict(
            os.environ,
            {
                "HAPPYIMAGE_AUTH_KEY": "image-bearer-admin-key",
                "HAPPYIMAGE_SESSION_SECRET": "cookie-test-session-secret",
                "HAPPYIMAGE_FRONTEND_BASE_URL": "http://localhost:3000",
            },
            clear=False,
        ):
            with TestClient(create_app()) as client:
                response = client.get(
                    f"/images/{image_rel}",
                    headers={"Authorization": "Bearer image-bearer-admin-key"},
                )

                assert response.status_code == 200, response.text
                assert response.headers["content-type"] == "image/png"
    finally:
        image_path.unlink(missing_ok=True)


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
