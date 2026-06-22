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

    def test_prefixed_dotenv_loads_happytoken_settings_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            dotenv_path = Path(tmp_dir) / ".env"
            dotenv_path.write_text(
                "\n".join(
                    [
                        "HAPPYTOKEN_SESSION_SECRET=dotenv-session-secret",
                        "HAPPYTOKEN_FRONTEND_BASE_URL=https://image.example.com",
                        "STORAGE_BACKEND=sqlite",
                    ]
                ),
                encoding="utf-8",
            )

            module = self.config_module
            old_dotenv = module.DOTENV_FILE
            old_session_secret = module.os.environ.get("HAPPYTOKEN_SESSION_SECRET")
            old_frontend_base_url = module.os.environ.get("HAPPYTOKEN_FRONTEND_BASE_URL")
            old_storage = module.os.environ.get("STORAGE_BACKEND")
            try:
                module.DOTENV_FILE = dotenv_path
                for key in [
                    "HAPPYTOKEN_SESSION_SECRET",
                    "HAPPYTOKEN_FRONTEND_BASE_URL",
                    "STORAGE_BACKEND",
                ]:
                    module.os.environ.pop(key, None)

                module._load_prefixed_dotenv()
                store = module.ConfigStore(Path(tmp_dir) / "config.json")

                self.assertEqual(store.session_secret, "dotenv-session-secret")
                self.assertEqual(store.frontend_base_url, "https://image.example.com")
                self.assertIsNone(module.os.environ.get("STORAGE_BACKEND"))
            finally:
                module.DOTENV_FILE = old_dotenv
                for key, value in {
                    "HAPPYTOKEN_SESSION_SECRET": old_session_secret,
                    "HAPPYTOKEN_FRONTEND_BASE_URL": old_frontend_base_url,
                    "STORAGE_BACKEND": old_storage,
                }.items():
                    if value is None:
                        module.os.environ.pop(key, None)
                    else:
                        module.os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
