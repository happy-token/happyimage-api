from __future__ import annotations

import os
import uuid
from unittest import mock

from fastapi.testclient import TestClient

import api.system as system_api
from api.app import create_app
from services.auth_service import auth_service
from services.config import config


def _runtime_config(**overrides: object):
    values: dict[str, object] = {
        "session_secret": "cookie-test-session-secret",
        "public_app_url": "http://localhost:3000",
        "local_password_login_enabled": True,
    }
    values.update(overrides)
    return mock.patch.dict(config.data, values, clear=False)


def _create_password_account(
    role: str = "admin", prefix: str = "account"
) -> tuple[str, str]:
    name = f"{prefix}-{uuid.uuid4().hex[:8]}"
    password = f"{prefix}-password-{uuid.uuid4().hex}"
    auth_service.create_key_with_value(role=role, name=name, key=password)
    return name, password


def _login_password(client: TestClient, role: str = "admin", prefix: str = "account"):
    name, password = _create_password_account(role=role, prefix=prefix)
    response = client.post(
        "/api/auth/login", json={"email": name, "password": password}
    )
    assert response.status_code == 200, response.text
    return name, password, response


def test_password_login_disabled_by_default_returns_unified_login_error():
    name, password = _create_password_account(role="admin", prefix="disabled-login")
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("HAPPYTOKEN_LOCAL_PASSWORD_LOGIN_ENABLED", None)
        with mock.patch.dict(config.data, {}, clear=False):
            config.data.pop("local_password_login_enabled", None)
            with TestClient(create_app()) as client:
                response = client.post(
                    "/api/auth/login", json={"email": name, "password": password}
                )

                assert response.status_code == 403, response.text
                assert response.json()["detail"]["error"] == "请使用统一登录入口"


def test_local_password_login_ignores_env_and_uses_config_switch():
    name, password = _create_password_account(role="admin", prefix="env-disabled-login")
    with (
        mock.patch.dict(
            os.environ,
            {"HAPPYTOKEN_LOCAL_PASSWORD_LOGIN_ENABLED": "true"},
            clear=False,
        ),
        _runtime_config(local_password_login_enabled=False),
    ):
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/auth/login", json={"email": name, "password": password}
            )

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["error"] == "请使用统一登录入口"


def test_password_login_can_be_enabled_for_emergency_ops():
    with _runtime_config():
        with TestClient(create_app()) as client:
            response = _login_password(client, prefix="emergency-admin")[2]

            assert response.status_code == 200, response.text
            assert response.json()["role"] == "admin"


def test_register_disabled_even_when_registration_enabled():
    with mock.patch.dict(
        os.environ,
        {"HAPPYTOKEN_REGISTRATION_ENABLED": "true"},
        clear=False,
    ):
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/auth/register",
                json={
                    "name": f"register-{uuid.uuid4().hex[:8]}",
                    "email": "creator@example.com",
                    "password": "register-password",
                    "confirm_password": "register-password",
                },
            )

            assert response.status_code == 403, response.text
            assert response.json()["detail"]["error"] == "注册请使用统一登录入口"


def test_registration_switch_ignores_env_and_uses_config_value():
    with (
        mock.patch.dict(
            os.environ,
            {"HAPPYTOKEN_REGISTRATION_ENABLED": "true"},
            clear=False,
        ),
        mock.patch.dict(config.data, {"registration_enabled": False}, clear=False),
    ):
        assert system_api._registration_enabled() is False

    with (
        mock.patch.dict(
            os.environ,
            {"HAPPYTOKEN_REGISTRATION_ENABLED": "false"},
            clear=False,
        ),
        mock.patch.dict(config.data, {"registration_enabled": True}, clear=False),
    ):
        assert system_api._registration_enabled() is True


def test_password_login_sets_cookie_and_cookie_authenticates_admin_api():
    with _runtime_config():
        with TestClient(create_app()) as client:
            login_response = _login_password(client, prefix="cookie-admin")[2]
            assert "httponly" in login_response.headers.get("set-cookie", "").lower()

            settings_response = client.get("/api/settings")

            assert settings_response.status_code == 200, settings_response.text
            assert "config" in settings_response.json()


def test_session_accepts_bearer_token_when_cookie_is_missing():
    with _runtime_config():
        with TestClient(create_app()) as client:
            _, password = _create_password_account(role="admin", prefix="bearer-admin")
            response = client.get(
                "/api/auth/session",
                headers={"Authorization": f"Bearer {password}"},
            )

            assert response.status_code == 200, response.text
            assert response.json()["role"] == "admin"


def test_admin_created_user_does_not_include_image_quota():
    with _runtime_config():
        with TestClient(create_app()) as client:
            _login_password(client, prefix="quota-admin")

            user_name = f"user-{uuid.uuid4().hex[:8]}"
            create_response = client.post("/api/auth/users", json={"name": user_name})
            assert create_response.status_code == 200, create_response.text
            item = create_response.json()["item"]
            assert "image_quota" not in item
            assert item["watermark_unlocked"] is False

            update_response = client.post(
                f"/api/auth/users/{item['id']}",
                json={"watermark_unlocked": True},
            )
            assert update_response.status_code == 200, update_response.text
            assert update_response.json()["item"]["watermark_unlocked"] is True


def test_user_profile_can_update_watermark_label():
    with _runtime_config():
        with TestClient(create_app()) as client:
            _login_password(client, prefix="profile-admin")

            user_name = f"profile-{uuid.uuid4().hex[:8]}"
            user_key = f"profile-key-{uuid.uuid4().hex}"
            create_response = client.post(
                "/api/auth/users", json={"name": user_name, "key": user_key}
            )
            assert create_response.status_code == 200, create_response.text

            user_login_response = client.post(
                "/api/auth/login", json={"email": user_name, "password": user_key}
            )
            assert user_login_response.status_code == 200, user_login_response.text

            update_response = client.patch(
                "/api/auth/profile", json={"watermark_label": "Happy Creator"}
            )
            assert update_response.status_code == 200, update_response.text
            payload = update_response.json()
            assert payload["user"]["watermark_label"] == "Happy Creator"
            assert payload["user"]["watermark_unlocked"] is False


def test_user_profile_model_providers_can_be_selected_and_preserve_keys():
    with _runtime_config():
        with TestClient(create_app()) as client:
            _login_password(client, prefix="provider-admin")

            user_name = f"provider-{uuid.uuid4().hex[:8]}"
            user_key = f"provider-key-{uuid.uuid4().hex}"
            create_response = client.post(
                "/api/auth/users", json={"name": user_name, "key": user_key}
            )
            assert create_response.status_code == 200, create_response.text

            user_login_response = client.post(
                "/api/auth/login", json={"email": user_name, "password": user_key}
            )
            assert user_login_response.status_code == 200, user_login_response.text

            save_response = client.patch(
                "/api/auth/profile",
                json={
                    "model_providers": [
                        {
                            "id": "provider-a",
                            "type": "newapi",
                            "base_url": "https://a.example.com/v1",
                            "api_key": "sk-a",
                            "selected": False,
                        },
                        {
                            "id": "provider-b",
                            "type": "newapi",
                            "base_url": "https://b.example.com/v1",
                            "api_key": "sk-b",
                            "selected": True,
                        },
                    ]
                },
            )
            assert save_response.status_code == 200, save_response.text
            assert (
                save_response.json()["user"]["model_base_url"]
                == "https://b.example.com/v1"
            )

            switch_response = client.patch(
                "/api/auth/profile",
                json={
                    "model_providers": [
                        {
                            "id": "provider-a",
                            "type": "newapi",
                            "base_url": "https://a.example.com/v1",
                            "api_key_configured": True,
                            "selected": True,
                        },
                        {
                            "id": "provider-b",
                            "type": "newapi",
                            "base_url": "https://b.example.com/v1",
                            "api_key_configured": True,
                            "selected": False,
                        },
                    ]
                },
            )
            assert switch_response.status_code == 200, switch_response.text
            payload = switch_response.json()
            assert payload["user"]["model_base_url"] == "https://a.example.com/v1"
            assert payload["user"]["model_api_key_configured"] is True
            assert [
                item["selected"] for item in payload["user"]["model_providers"]
            ] == [True, False]


def test_user_profile_preferences_sync_to_account():
    with _runtime_config():
        with TestClient(create_app()) as client:
            user_name, user_key = _create_password_account(
                role="user", prefix="prefs-user"
            )
            login_response = client.post(
                "/api/auth/login", json={"email": user_name, "password": user_key}
            )
            assert login_response.status_code == 200, login_response.text

            update_response = client.patch(
                "/api/auth/profile",
                json={
                    "preferences": {
                        "theme": "dark",
                        "language": "en-US",
                        "image_ratio": "9:16",
                        "image_tier": "2k",
                        "image_quality": "high",
                        "image_model": "gpt-image-2",
                        "sidebar_collapsed": True,
                        "sidebar_width": 320,
                        "unexpected": "ignored",
                    }
                },
            )
            assert update_response.status_code == 200, update_response.text
            preferences = update_response.json()["user"]["preferences"]
            assert preferences == {
                "theme": "dark",
                "language": "en-US",
                "image_ratio": "9:16",
                "image_tier": "2k",
                "image_quality": "high",
                "image_model": "gpt-image-2",
                "sidebar_collapsed": True,
                "sidebar_width": 320,
            }

            session_response = client.get("/api/auth/session")
            assert session_response.status_code == 200, session_response.text
            assert session_response.json()["user"]["preferences"]["theme"] == "dark"


def test_admin_profile_can_sync_preferences_without_provider_fields():
    with _runtime_config():
        with TestClient(create_app()) as client:
            _login_password(client, prefix="prefs-admin")

            update_response = client.patch(
                "/api/auth/profile",
                json={
                    "model_base_url": "https://ignored.example/v1",
                    "preferences": {"theme": "light", "language": "zh-CN"},
                },
            )
            assert update_response.status_code == 200, update_response.text
            payload = update_response.json()
            assert payload["user"]["preferences"] == {
                "theme": "light",
                "language": "zh-CN",
            }
            assert payload["user"]["model_base_url"] == ""


def test_test_user_password_login_is_case_insensitive():
    with (
        mock.patch.dict(os.environ, {"HAPPYTOKEN_TEST_ACCOUNTS_ENABLED": "false"}, clear=False),
        _runtime_config(test_accounts_enabled=True),
    ):
        fake_identity = {"id": "user", "name": "user", "role": "user"}
        with mock.patch(
            "api.support.auth_service.authenticate", return_value=fake_identity
        ):
            with TestClient(create_app()) as client:
                response = client.post(
                    "/api/auth/login", json={"email": "User", "password": "User"}
                )

                assert response.status_code == 200, response.text
                assert response.json()["role"] == "user"


def test_test_user_password_login_ignores_env_when_config_disabled():
    with (
        mock.patch.dict(
            os.environ,
            {"HAPPYTOKEN_TEST_ACCOUNTS_ENABLED": "true"},
            clear=False,
        ),
        _runtime_config(test_accounts_enabled=False),
    ):
        with mock.patch("api.support.auth_service.authenticate", return_value=None):
            with TestClient(create_app()) as client:
                response = client.post(
                    "/api/auth/login", json={"email": "User", "password": "User"}
                )

    assert response.status_code == 401, response.text
    assert response.json()["detail"]["error"] == "账号或密码不正确"


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
        with _runtime_config(local_password_login_enabled=False):
            with TestClient(create_app()) as client:
                _, password = _create_password_account(
                    role="admin", prefix="image-bearer"
                )
                response = client.get(
                    f"/images/{image_rel}",
                    headers={"Authorization": f"Bearer {password}"},
                )

                assert response.status_code == 200, response.text
                assert response.headers["content-type"] == "image/png"
    finally:
        image_path.unlink(missing_ok=True)


def test_cookie_auth_rejects_untrusted_write_origin():
    with _runtime_config():
        with TestClient(create_app()) as client:
            _login_password(client, prefix="origin-admin")

            response = client.post(
                "/api/settings",
                json={},
                headers={"Origin": "http://evil.example"},
            )

            assert response.status_code == 403, response.text
