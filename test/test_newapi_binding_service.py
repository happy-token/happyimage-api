from __future__ import annotations

from unittest import mock

from services.config import ConfigStore, CONFIG_FILE


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
