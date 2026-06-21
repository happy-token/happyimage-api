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
            ROOT_CONFIG_FILE.write_text(json.dumps({"auth-key": "test-auth"}), encoding="utf-8")
            cls._created_root_config = True

        from services import config as config_module

        cls.config_module = config_module

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._created_root_config and ROOT_CONFIG_FILE.exists():
            ROOT_CONFIG_FILE.unlink()

    def test_load_settings_ignores_directory_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            data_dir = base_dir / "data"
            config_dir = base_dir / "config.json"
            os_auth_key = "env-auth"

            config_dir.mkdir()

            module = self.config_module
            old_base_dir = module.BASE_DIR
            old_data_dir = module.DATA_DIR
            old_config_file = module.CONFIG_FILE
            old_env_auth_key = module.os.environ.get("HAPPYIMAGE_AUTH_KEY")
            try:
                module.BASE_DIR = base_dir
                module.DATA_DIR = data_dir
                module.CONFIG_FILE = config_dir
                module.os.environ["HAPPYIMAGE_AUTH_KEY"] = os_auth_key

                settings = module._load_settings()

                self.assertEqual(settings.auth_key, os_auth_key)
                self.assertEqual(settings.refresh_account_interval_minute, 5)
            finally:
                module.BASE_DIR = old_base_dir
                module.DATA_DIR = old_data_dir
                module.CONFIG_FILE = old_config_file
                if old_env_auth_key is None:
                    module.os.environ.pop("HAPPYIMAGE_AUTH_KEY", None)
                else:
                    module.os.environ["HAPPYIMAGE_AUTH_KEY"] = old_env_auth_key

    def test_model_gateway_key_is_preserved_when_update_payload_is_blank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "auth-key": "test-auth",
                        "model_gateway_base_url": "https://old.example/v1",
                        "model_gateway_api_key": "sk-existing",
                    }
                ),
                encoding="utf-8",
            )

            module = self.config_module
            old_base_url = module.os.environ.get("HAPPYIMAGE_MODEL_GATEWAY_BASE_URL")
            old_api_key = module.os.environ.get("HAPPYIMAGE_MODEL_GATEWAY_API_KEY")
            try:
                module.os.environ.pop("HAPPYIMAGE_MODEL_GATEWAY_BASE_URL", None)
                module.os.environ.pop("HAPPYIMAGE_MODEL_GATEWAY_API_KEY", None)

                store = module.ConfigStore(config_path)
                response = store.update(
                    {
                        "model_gateway_base_url": "https://new.example/v1/",
                        "model_gateway_api_key": "",
                        "model_gateway_api_key_configured": True,
                    }
                )

                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["model_gateway_base_url"], "https://new.example/v1")
                self.assertEqual(saved["model_gateway_api_key"], "sk-existing")
                self.assertTrue(response["model_gateway_api_key_configured"])
                self.assertNotIn("model_gateway_api_key", response)
            finally:
                if old_base_url is None:
                    module.os.environ.pop("HAPPYIMAGE_MODEL_GATEWAY_BASE_URL", None)
                else:
                    module.os.environ["HAPPYIMAGE_MODEL_GATEWAY_BASE_URL"] = old_base_url
                if old_api_key is None:
                    module.os.environ.pop("HAPPYIMAGE_MODEL_GATEWAY_API_KEY", None)
                else:
                    module.os.environ["HAPPYIMAGE_MODEL_GATEWAY_API_KEY"] = old_api_key


if __name__ == "__main__":
    unittest.main()
