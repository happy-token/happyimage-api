from __future__ import annotations

from unittest import mock

from services.auth_service import AuthService
from services.config import ConfigStore, CONFIG_FILE
from services.newapi_binding_service import NewAPIBindingService, newapi_binding_service
from services.storage.json_storage import JSONStorageBackend


def test_newapi_binding_settings_from_env():
    with mock.patch.dict(
        "os.environ",
        {
            "HAPPYTOKEN_NEWAPI_BASE_URL": "https://gateway.happy-token.cn/",
            "HAPPYTOKEN_NEWAPI_MANAGEMENT_URL": "https://gateway.happy-token.cn",
            "HAPPYTOKEN_NEWAPI_PROVISION_URL": "http://newapi:3000/api/internal/happyimage/bind-token",
            "HAPPYTOKEN_NEWAPI_PROVISION_SECRET": "secret",
            "HAPPYTOKEN_NEWAPI_TOKEN_NAME": "HappyImage Default",
        },
        clear=False,
    ):
        store = ConfigStore(CONFIG_FILE)
        settings = store.get_newapi_binding_settings()

    assert settings == {
        "base_url": "https://gateway.happy-token.cn",
        "management_url": "https://gateway.happy-token.cn",
        "provision_url": "http://newapi:3000/api/internal/happyimage/bind-token",
        "provision_secret_configured": True,
        "provision_secret": "secret",
        "token_name": "HappyImage Default",
        "enabled": True,
    }


def test_newapi_binding_defaults_to_pending_safe_values():
    with mock.patch.dict("os.environ", {}, clear=True):
        store = ConfigStore(CONFIG_FILE)
        settings = store.get_newapi_binding_settings()

    assert settings["base_url"] == "https://gateway.happy-token.cn"
    assert settings["management_url"] == "https://gateway.happy-token.cn"
    assert settings["token_name"] == "HappyImage Default"
    assert settings["enabled"] is False
    assert settings["provision_secret"] == ""
    assert settings["provision_secret_configured"] is False


def test_apply_newapi_default_provider_sets_selected_provider(tmp_path):
    storage = JSONStorageBackend(tmp_path / "accounts.json")
    service = AuthService(storage)
    user, _raw_key = service.create_key(role="user", name="Creator")

    updated = service.apply_newapi_default_provider(
        str(user["id"]),
        base_url="https://gateway.happy-token.cn",
        api_key="sk-user-token",
    )

    assert updated is not None
    assert updated["model_provider"] == "newapi"
    assert updated["model_base_url"] == "https://gateway.happy-token.cn"
    assert updated["model_api_key_configured"] is True
    assert updated["model_providers"] == [
        {
            "id": "newapi-default",
            "type": "newapi",
            "base_url": "https://gateway.happy-token.cn",
            "api_key_configured": True,
            "selected": True,
        }
    ]


def test_apply_newapi_default_provider_preserves_other_providers(tmp_path):
    storage = JSONStorageBackend(tmp_path / "accounts.json")
    service = AuthService(storage)
    user, _raw_key = service.create_key(role="user", name="Creator Two")
    service.update_key(
        str(user["id"]),
        {
            "model_providers": [
                {
                    "id": "manual-provider",
                    "type": "newapi",
                    "base_url": "https://manual.example.com",
                    "api_key": "sk-manual",
                    "selected": True,
                }
            ]
        },
        role="user",
    )

    updated = service.apply_newapi_default_provider(
        str(user["id"]),
        base_url="https://gateway.happy-token.cn",
        api_key="sk-user-token",
    )

    assert updated is not None
    providers = updated["model_providers"]
    assert [item["id"] for item in providers] == ["manual-provider", "newapi-default"]
    assert [item["selected"] for item in providers] == [False, True]


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object], text: str = "{}"):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> dict[str, object]:
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None):
        self.response = response or FakeResponse(200, {"ok": True, "token": "sk-default"})
        self.error = error
        self.posts: list[dict[str, object]] = []
        self.closed = False

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.posts.append({"url": url, **kwargs})
        if self.error:
            raise self.error
        return self.response

    def close(self) -> None:
        self.closed = True


def _enabled_settings() -> dict[str, object]:
    return {
        "enabled": True,
        "base_url": "https://gateway.happy-token.cn/",
        "management_url": "https://gateway.happy-token.cn/manage/",
        "provision_url": "http://newapi:3000/api/internal/happyimage/bind-token",
        "provision_secret": "provision-secret",
        "provision_secret_configured": True,
        "token_name": "HappyImage Default",
    }


def test_newapi_binding_returns_pending_when_disabled_or_unconfigured():
    service = NewAPIBindingService(
        settings={**_enabled_settings(), "enabled": False},
        session_factory=lambda: FakeSession(),
    )

    result = service.ensure_default_token(
        provider="casdoor",
        subject="casdoor-sub",
        email="creator@example.com",
        name="Creator",
    )

    assert result == {
        "ok": False,
        "status": "pending",
        "message": "NewAPI provisioning endpoint is not configured",
        "base_url": "https://gateway.happy-token.cn",
        "management_url": "https://gateway.happy-token.cn/manage",
    }

    service = NewAPIBindingService(
        settings={**_enabled_settings(), "provision_secret": ""},
        session_factory=lambda: FakeSession(),
    )

    result = service.ensure_default_token(
        provider="casdoor",
        subject="casdoor-sub",
        email="creator@example.com",
        name="Creator",
    )

    assert result["ok"] is False
    assert result["status"] == "pending"
    assert result["base_url"] == "https://gateway.happy-token.cn"
    assert result["management_url"] == "https://gateway.happy-token.cn/manage"


def test_newapi_binding_pending_response_defaults_missing_urls():
    service = NewAPIBindingService(
        settings={
            "enabled": False,
            "base_url": "",
            "management_url": "",
            "provision_url": "",
            "provision_secret": "",
        },
        session_factory=lambda: FakeSession(),
    )

    result = service.ensure_default_token(
        provider="casdoor",
        subject="casdoor-sub",
        email="creator@example.com",
        name="Creator",
    )

    assert result == {
        "ok": False,
        "status": "pending",
        "message": "NewAPI provisioning endpoint is not configured",
        "base_url": "https://gateway.happy-token.cn",
        "management_url": "https://gateway.happy-token.cn",
    }


def test_newapi_binding_calls_configured_provisioning_endpoint_with_auth_and_payload():
    session = FakeSession(
        FakeResponse(
            200,
            {
                "ok": True,
                "user_id": "newapi-user-id",
                "token_id": "newapi-token-id",
                "token": "sk-user-token",
                "base_url": "https://gateway.happy-token.cn/v1/",
            },
        )
    )
    service = NewAPIBindingService(settings=_enabled_settings(), session_factory=lambda: session)

    service.ensure_default_token(
        provider="casdoor",
        subject="casdoor-sub",
        email="creator@example.com",
        name="Creator",
    )

    assert session.posts == [
        {
            "url": "http://newapi:3000/api/internal/happyimage/bind-token",
            "headers": {
                "Authorization": "Bearer provision-secret",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            "json": {
                "provider": "casdoor",
                "subject": "casdoor-sub",
                "email": "creator@example.com",
                "name": "Creator",
                "token_name": "HappyImage Default",
            },
            "timeout": 20,
        }
    ]


def test_newapi_binding_exports_module_singleton():
    assert isinstance(newapi_binding_service, NewAPIBindingService)


def test_newapi_binding_closes_session():
    session = FakeSession()
    service = NewAPIBindingService(settings=_enabled_settings(), session_factory=lambda: session)

    service.ensure_default_token(
        provider="casdoor",
        subject="casdoor-sub",
        email="creator@example.com",
        name="Creator",
    )

    assert session.closed is True


def test_newapi_binding_successful_response_exposes_token_and_base_url():
    service = NewAPIBindingService(
        settings=_enabled_settings(),
        session_factory=lambda: FakeSession(
            FakeResponse(
                200,
                {
                    "ok": True,
                    "user_id": "newapi-user-id",
                    "token_id": "newapi-token-id",
                    "token": "sk-user-token",
                    "base_url": "https://gateway.happy-token.cn/v1/",
                },
            )
        ),
    )

    result = service.ensure_default_token(
        provider="casdoor",
        subject="casdoor-sub",
        email="creator@example.com",
        name="Creator",
    )

    assert result == {
        "ok": True,
        "status": "configured",
        "user_id": "newapi-user-id",
        "token_id": "newapi-token-id",
        "token": "sk-user-token",
        "base_url": "https://gateway.happy-token.cn/v1",
        "management_url": "https://gateway.happy-token.cn/manage",
    }


def test_newapi_binding_non_200_failure_is_redacted():
    session = FakeSession(
        FakeResponse(
            500,
            {"ok": False, "message": "secret=provision-secret token=sk-upstream-token"},
            text='{"message":"secret=provision-secret token=sk-upstream-token"}',
        )
    )
    service = NewAPIBindingService(settings=_enabled_settings(), session_factory=lambda: session)

    result = service.ensure_default_token(
        provider="casdoor",
        subject="casdoor-sub",
        email="creator@example.com",
        name="Creator",
    )

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert result["http_status"] == 500
    result_text = str(result)
    assert "provision-secret" not in result_text
    assert "sk-upstream-token" not in result_text


def test_newapi_binding_exception_failure_is_redacted_and_closes_session():
    session = FakeSession(error=RuntimeError("secret=provision-secret token=sk-exception-token"))
    service = NewAPIBindingService(settings=_enabled_settings(), session_factory=lambda: session)

    result = service.ensure_default_token(
        provider="casdoor",
        subject="casdoor-sub",
        email="creator@example.com",
        name="Creator",
    )

    assert result == {
        "ok": False,
        "status": "failed",
        "message": "NewAPI provisioning request failed",
    }
    assert session.closed is True
    result_text = str(result)
    assert "provision-secret" not in result_text
    assert "sk-exception-token" not in result_text


def test_newapi_binding_missing_token_failure_is_redacted():
    session = FakeSession(
        FakeResponse(
            200,
            {"ok": True, "message": "secret=provision-secret token=sk-missing-token"},
            text='{"ok":true,"message":"secret=provision-secret token=sk-missing-token"}',
        )
    )
    service = NewAPIBindingService(settings=_enabled_settings(), session_factory=lambda: session)

    result = service.ensure_default_token(
        provider="casdoor",
        subject="casdoor-sub",
        email="creator@example.com",
        name="Creator",
    )

    assert result == {
        "ok": False,
        "status": "failed",
        "message": "NewAPI provisioning returned an invalid response",
    }
    result_text = str(result)
    assert "provision-secret" not in result_text
    assert "sk-missing-token" not in result_text
