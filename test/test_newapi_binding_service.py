from __future__ import annotations

import json
from unittest import mock

from services.auth_service import AuthService
from services.config import ConfigStore
from services.newapi_binding_service import NewAPIBindingService, newapi_binding_service
from services.storage.json_storage import JSONStorageBackend


def test_newapi_binding_settings_use_model_gateway_config_and_ignore_env(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "model_gateway": {
                    "gateway_api_base_url": "https://config-gateway.example.com/",
                    "gateway_management_url": "https://config-admin.example.com/",
                    "provision_url": "http://configured-newapi:3000/api/internal/happyimage/bind-token",
                    "provision_secret": "configured-secret",
                    "token_name": "Configured Token",
                    "sql_dsn": "",
                }
            }
        ),
        encoding="utf-8",
    )

    with mock.patch.dict(
        "os.environ",
        {
            "HAPPYTOKEN_NEWAPI_BASE_URL": "https://env-gateway.example.com/",
            "HAPPYTOKEN_NEWAPI_MANAGEMENT_URL": "https://env-admin.example.com",
            "HAPPYTOKEN_NEWAPI_PROVISION_URL": "http://env-newapi:3000/bind-token",
            "HAPPYTOKEN_NEWAPI_PROVISION_SECRET": "env-secret",
            "HAPPYTOKEN_NEWAPI_TOKEN_NAME": "Env Token",
            "HAPPYTOKEN_NEWAPI_SQL_DSN": "postgresql://env:secret@db/new-api",
        },
        clear=False,
    ):
        store = ConfigStore(config_path)
        settings = store.get_newapi_binding_settings()

    assert settings["gateway_api_base_url"] == "https://config-gateway.example.com/v1"
    assert settings["gateway_management_url"] == "https://config-admin.example.com"
    assert settings["base_url"] == "https://config-gateway.example.com/v1"
    assert settings["management_url"] == "https://config-admin.example.com"
    assert settings["provision_url"] == "http://configured-newapi:3000/api/internal/happyimage/bind-token"
    assert settings["provision_secret"] == "configured-secret"
    assert settings["provision_secret_configured"] is True
    assert settings["sql_dsn"] == ""
    assert settings["sql_dsn_configured"] is False
    assert settings["token_name"] == "Configured Token"
    assert settings["enabled"] is True


def test_newapi_binding_settings_remove_v1_from_management_url(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "model_gateway": {
                    "gateway_api_base_url": "https://config-gateway.example.com/v1/",
                    "gateway_management_url": "https://config-admin.example.com/v1/",
                }
            }
        ),
        encoding="utf-8",
    )

    settings = ConfigStore(config_path).get_newapi_binding_settings()

    assert settings["gateway_api_base_url"] == "https://config-gateway.example.com/v1"
    assert settings["gateway_management_url"] == "https://config-admin.example.com"
    assert settings["base_url"] == "https://config-gateway.example.com/v1"
    assert settings["management_url"] == "https://config-admin.example.com"


def test_newapi_binding_settings_use_legacy_newapi_binding_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "newapi_binding": {
                    "base_url": "https://legacy-gateway.example.com/",
                    "management_url": "https://legacy-admin.example.com/manage/",
                    "provision_url": "http://legacy-newapi:3000/api/internal/happyimage/bind-token",
                    "provision_secret": "legacy-secret",
                    "token_name": "Legacy Token",
                    "sql_dsn": "postgresql://newapi:secret@127.0.0.1:15433/new-api",
                }
            }
        ),
        encoding="utf-8",
    )

    with mock.patch.dict(
        "os.environ",
        {
            "HAPPYTOKEN_NEWAPI_BASE_URL": "https://env-gateway.example.com/",
            "HAPPYIMAGE_NEWAPI_MANAGEMENT_URL": "https://env-admin.example.com",
            "HAPPYIMAGE_NEWAPI_SQL_DSN": "postgresql://env:secret@db/new-api",
        },
        clear=False,
    ):
        store = ConfigStore(config_path)
        settings = store.get_newapi_binding_settings()

    assert settings["gateway_api_base_url"] == "https://legacy-gateway.example.com/v1"
    assert settings["gateway_management_url"] == "https://legacy-admin.example.com/manage"
    assert settings["base_url"] == "https://legacy-gateway.example.com/v1"
    assert settings["management_url"] == "https://legacy-admin.example.com/manage"
    assert settings["provision_url"] == "http://legacy-newapi:3000/api/internal/happyimage/bind-token"
    assert settings["provision_secret"] == "legacy-secret"
    assert settings["provision_secret_configured"] is True
    assert settings["sql_dsn"] == "postgresql://newapi:secret@127.0.0.1:15433/new-api"
    assert settings["sql_dsn_configured"] is True
    assert settings["token_name"] == "Legacy Token"
    assert settings["enabled"] is True


def test_newapi_binding_settings_ignore_env_when_config_empty(tmp_path):
    with mock.patch.dict(
        "os.environ",
        {
            "HAPPYTOKEN_NEWAPI_PROVISION_URL": "http://env-newapi:3000/bind-token",
            "HAPPYTOKEN_NEWAPI_PROVISION_SECRET": "env-secret",
            "HAPPYTOKEN_NEWAPI_SQL_DSN": "postgresql://env:secret@db/new-api",
            "HAPPYIMAGE_NEWAPI_BASE_URL": "https://legacy-env-gateway.example.com",
        },
        clear=False,
    ):
        store = ConfigStore(tmp_path / "config.json")
        settings = store.get_newapi_binding_settings()

    assert settings == {
        "gateway_api_base_url": "https://gateway.happy-token.cn/v1",
        "gateway_management_url": "https://gateway.happy-token.cn",
        "base_url": "https://gateway.happy-token.cn/v1",
        "management_url": "https://gateway.happy-token.cn",
        "provision_url": "",
        "provision_secret_configured": False,
        "provision_secret": "",
        "sql_dsn": "",
        "sql_dsn_configured": False,
        "token_name": "HappyImage Default",
        "enabled": False,
    }


def test_newapi_binding_defaults_to_pending_safe_values(tmp_path):
    with mock.patch.dict("os.environ", {}, clear=True):
        store = ConfigStore(tmp_path / "config.json")
        settings = store.get_newapi_binding_settings()

    assert settings["gateway_api_base_url"] == "https://gateway.happy-token.cn/v1"
    assert settings["gateway_management_url"] == "https://gateway.happy-token.cn"
    assert settings["base_url"] == "https://gateway.happy-token.cn/v1"
    assert settings["management_url"] == "https://gateway.happy-token.cn"
    assert settings["token_name"] == "HappyImage Default"
    assert settings["enabled"] is False
    assert settings["provision_secret"] == ""
    assert settings["provision_secret_configured"] is False
    assert settings["sql_dsn"] == ""
    assert settings["sql_dsn_configured"] is False


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
                "protocol": "openai",
                "base_url": "https://gateway.happy-token.cn",
                "models": [],
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
    def __init__(
        self, response: FakeResponse | None = None, error: Exception | None = None
    ):
        self.response = response or FakeResponse(
            200, {"ok": True, "token": "sk-default"}
        )
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


class FakeCursor:
    def __init__(self, connection: "FakeSQLConnection") -> None:
        self.connection = connection
        self.next_result: tuple[object, ...] | None = None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: object = ()) -> None:
        self.connection.queries.append((query, params))
        compact = " ".join(query.split()).lower()
        if "select id from users where oidc_id" in compact:
            self.next_result = (
                (self.connection.user_id,) if self.connection.user_id is not None else None
            )
        elif "select id, key from tokens" in compact:
            self.next_result = (
                (self.connection.token_id, self.connection.token)
                if self.connection.token_id is not None
                else None
            )
        elif "select access_token from users" in compact:
            self.next_result = (self.connection.access_token,)
        elif "insert into users" in compact:
            self.next_result = (self.connection.created_user_id,)
        elif "insert into tokens" in compact:
            self.next_result = (self.connection.created_token_id,)
        else:
            self.next_result = None

    def fetchone(self) -> tuple[object, ...] | None:
        result = self.next_result
        self.next_result = None
        return result

    def fetchall(self) -> list[tuple[object, ...]]:
        return [
            (
                self.connection.token_id or self.connection.created_token_id,
                self.connection.token,
                1,
                "HappyImage Default",
                100,
                0,
                -1,
                0,
                True,
                0,
            )
        ]


class FakeSQLConnection:
    def __init__(
        self,
        *,
        user_id: int | None = 10,
        token_id: int | None = 20,
        token: str = "raw-token",
    ) -> None:
        self.user_id = user_id
        self.token_id = token_id
        self.token = token
        self.access_token = "newapi-access-token"
        self.created_user_id = 11
        self.created_token_id = 21
        self.queries: list[tuple[str, object]] = []
        self.closed = False

    def __enter__(self) -> "FakeSQLConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


def _enabled_settings() -> dict[str, object]:
    return {
        "enabled": True,
        "gateway_api_base_url": "https://gateway.happy-token.cn/",
        "gateway_management_url": "https://gateway.happy-token.cn/manage/",
        "base_url": "https://legacy-gateway.example.com/",
        "management_url": "https://legacy-admin.example.com/",
        "provision_url": "http://newapi:3000/api/internal/happyimage/bind-token",
        "provision_secret": "provision-secret",
        "provision_secret_configured": True,
        "sql_dsn": "",
        "sql_dsn_configured": False,
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
        "base_url": "https://gateway.happy-token.cn/v1",
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
    assert result["base_url"] == "https://gateway.happy-token.cn/v1"
    assert result["management_url"] == "https://gateway.happy-token.cn/manage"


def test_newapi_binding_prefers_unified_gateway_url_names_over_aliases():
    service = NewAPIBindingService(
        settings={
            "enabled": False,
            "gateway_api_base_url": "https://unified-gateway.example.com/",
            "gateway_management_url": "https://unified-admin.example.com/v1/",
            "base_url": "https://legacy-gateway.example.com/",
            "management_url": "https://legacy-admin.example.com/",
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

    assert result["base_url"] == "https://unified-gateway.example.com/v1"
    assert result["management_url"] == "https://unified-admin.example.com"


def test_newapi_binding_preserves_legacy_gateway_url_aliases():
    service = NewAPIBindingService(
        settings={
            "enabled": False,
            "base_url": "https://legacy-gateway.example.com/",
            "management_url": "https://legacy-admin.example.com/v1/",
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

    assert result["base_url"] == "https://legacy-gateway.example.com/v1"
    assert result["management_url"] == "https://legacy-admin.example.com"


def test_newapi_binding_direct_sql_reuses_existing_user_and_token():
    connection = FakeSQLConnection(user_id=1, token_id=2, token="existing-token")
    service = NewAPIBindingService(
        settings={
            **_enabled_settings(),
            "provision_url": "",
            "provision_secret": "",
            "sql_dsn": "postgresql://newapi:secret@postgres:5432/new-api",
        },
        sql_connect_factory=lambda dsn: connection,
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
        "user_id": "1",
        "token_id": "2",
        "token": "sk-existing-token",
        "access_token": "newapi-access-token",
        "tokens": [
            {
                "id": 2,
                "key": "sk-existing-token",
                "status": 1,
                "name": "HappyImage Default",
                "created_time": 100,
                "accessed_time": 0,
                "expired_time": -1,
                "remain_quota": 0,
                "unlimited_quota": True,
                "used_quota": 0,
            }
        ],
        "base_url": "https://gateway.happy-token.cn/v1",
        "management_url": "https://gateway.happy-token.cn/manage",
    }
    assert connection.closed is True
    assert any("oidc_id" in query for query, _params in connection.queries)


def test_newapi_binding_direct_sql_creates_missing_user_and_token():
    connection = FakeSQLConnection(user_id=None, token_id=None)
    service = NewAPIBindingService(
        settings={
            **_enabled_settings(),
            "provision_url": "",
            "provision_secret": "",
            "sql_dsn": "postgresql://newapi:secret@postgres:5432/new-api",
        },
        sql_connect_factory=lambda dsn: connection,
    )

    result = service.ensure_default_token(
        provider="casdoor",
        subject="casdoor-sub",
        email="creator@example.com",
        name="Creator",
    )

    assert result["ok"] is True
    assert result["status"] == "configured"
    assert result["user_id"] == "11"
    assert result["token_id"] == "21"
    assert result["token"].startswith("sk-")
    assert result["access_token"] == "newapi-access-token"
    assert isinstance(result["tokens"], list)
    assert any("insert into users" in query.lower() for query, _params in connection.queries)
    assert any("insert into tokens" in query.lower() for query, _params in connection.queries)


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
        "base_url": "https://gateway.happy-token.cn/v1",
        "management_url": "https://gateway.happy-token.cn",
    }


def test_newapi_binding_pending_management_url_falls_back_to_base_url():
    service = NewAPIBindingService(
        settings={
            "enabled": False,
            "gateway_api_base_url": "https://custom.example/v1/",
            "gateway_management_url": "",
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

    assert result["base_url"] == "https://custom.example/v1"
    assert result["management_url"] == "https://custom.example"


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
    service = NewAPIBindingService(
        settings=_enabled_settings(), session_factory=lambda: session
    )

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
    service = NewAPIBindingService(
        settings=_enabled_settings(), session_factory=lambda: session
    )

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
    service = NewAPIBindingService(
        settings=_enabled_settings(), session_factory=lambda: session
    )

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
    session = FakeSession(
        error=RuntimeError("secret=provision-secret token=sk-exception-token")
    )
    service = NewAPIBindingService(
        settings=_enabled_settings(), session_factory=lambda: session
    )

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


def test_newapi_binding_session_factory_failure_is_redacted():
    def raise_session_error():
        raise RuntimeError("secret=provision-secret token=sk-session-token")

    service = NewAPIBindingService(
        settings=_enabled_settings(), session_factory=raise_session_error
    )

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
    result_text = str(result)
    assert "provision-secret" not in result_text
    assert "sk-session-token" not in result_text


def test_newapi_binding_missing_token_failure_is_redacted():
    session = FakeSession(
        FakeResponse(
            200,
            {"ok": True, "message": "secret=provision-secret token=sk-missing-token"},
            text='{"ok":true,"message":"secret=provision-secret token=sk-missing-token"}',
        )
    )
    service = NewAPIBindingService(
        settings=_enabled_settings(), session_factory=lambda: session
    )

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
