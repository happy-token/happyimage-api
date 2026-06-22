from __future__ import annotations

from unittest import mock

from services.auth_service import AuthService
from services.config import ConfigStore, CONFIG_FILE
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
