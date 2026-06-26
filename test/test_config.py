import json
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ROOT_CONFIG_FILE = ROOT_DIR / "config.json"


class ConfigLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._created_root_config = False
        if not ROOT_CONFIG_FILE.exists():
            ROOT_CONFIG_FILE.write_text(json.dumps({}), encoding="utf-8")
            cls._created_root_config = True

        from services import config as config_module

        cls.config_module = config_module

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._created_root_config and ROOT_CONFIG_FILE.exists():
            ROOT_CONFIG_FILE.unlink()

    def test_load_settings_without_auth_key_and_ignores_directory_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            data_dir = base_dir / "data"
            config_dir = base_dir / "config.json"

            config_dir.mkdir()

            module = self.config_module
            old_base_dir = module.BASE_DIR
            old_data_dir = module.DATA_DIR
            old_config_file = module.CONFIG_FILE
            try:
                module.BASE_DIR = base_dir
                module.DATA_DIR = data_dir
                module.CONFIG_FILE = config_dir

                settings = module._load_settings()

                self.assertEqual(settings.refresh_account_interval_minute, 5)
            finally:
                module.BASE_DIR = old_base_dir
                module.DATA_DIR = old_data_dir
                module.CONFIG_FILE = old_config_file

    def test_model_gateway_fields_are_not_saved_from_settings_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(json.dumps({}), encoding="utf-8")

            store = self.config_module.ConfigStore(config_path)
            response = store.update(
                {
                    "model_gateway_provider": "openai_compatible",
                    "model_gateway_base_url": "https://gateway.example/v1/",
                    "model_gateway_api_key": "sk-provider",
                    "model_gateway_api_key_configured": True,
                }
            )

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertNotIn("model_gateway_provider", saved)
            self.assertNotIn("model_gateway_base_url", saved)
            self.assertNotIn("model_gateway_api_key", saved)
            self.assertNotIn("model_gateway_api_key_configured", response)

    def test_config_store_uses_storage_backend_for_runtime_settings(self) -> None:
        class MemoryStorage:
            def __init__(self) -> None:
                self.runtime_config: dict[str, object] = {}

            def load_accounts(self) -> list[dict[str, object]]:
                return []

            def save_accounts(self, accounts: list[dict[str, object]]) -> None:
                pass

            def load_auth_keys(self) -> list[dict[str, object]]:
                return []

            def save_auth_keys(self, auth_keys: list[dict[str, object]]) -> None:
                pass

            def load_runtime_config(self) -> dict[str, object]:
                return dict(self.runtime_config)

            def save_runtime_config(self, config: dict[str, object]) -> None:
                self.runtime_config = dict(config)

            def health_check(self) -> dict[str, object]:
                return {"status": "healthy"}

            def get_backend_info(self) -> dict[str, object]:
                return {"type": "memory"}

        store = self.config_module.ConfigStore(Path("ignored-config.json"), storage_backend=MemoryStorage())
        response = store.update(
            {
                "public_app_url": "https://image.example.com/",
                "api_public_url": "",
                "model_gateway": {
                    "gateway_api_base_url": "https://gateway.happy-token.cn/v1/",
                    "gateway_management_url": "",
                    "token_name": "HappyImage Default",
                },
            }
        )

        self.assertEqual(response["public_app_url"], "https://image.example.com")
        self.assertEqual(response["api_public_url"], "")
        self.assertEqual(response["external_api_url"], "https://image.example.com")
        self.assertEqual(response["model_gateway"]["gateway_api_base_url"], "https://gateway.happy-token.cn/v1")
        self.assertEqual(response["model_gateway"]["gateway_management_url"], "https://gateway.happy-token.cn")

    def test_service_runtime_settings_ignore_happytoken_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            module = self.config_module
            old_session_secret = module.os.environ.get("HAPPYTOKEN_SESSION_SECRET")
            old_frontend_base_url = module.os.environ.get("HAPPYTOKEN_FRONTEND_BASE_URL")
            try:
                module.os.environ["HAPPYTOKEN_SESSION_SECRET"] = "env-session-secret"
                module.os.environ["HAPPYTOKEN_FRONTEND_BASE_URL"] = "https://env.example.com"

                store = module.ConfigStore(Path(tmp_dir) / "config.json")

                self.assertEqual(store.session_secret, "")
                self.assertEqual(store.public_app_url, "")
                self.assertEqual(store.frontend_base_url, "")
            finally:
                for key, value in {
                    "HAPPYTOKEN_SESSION_SECRET": old_session_secret,
                    "HAPPYTOKEN_FRONTEND_BASE_URL": old_frontend_base_url,
                }.items():
                    if value is None:
                        module.os.environ.pop(key, None)
                    else:
                        module.os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
