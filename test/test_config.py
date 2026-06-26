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

    def test_config_store_migrates_legacy_file_into_empty_storage_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = tmp_path / "config.json"
            runtime_config_path = tmp_path / "runtime_config.json"
            config_path.write_text(
                json.dumps({"public_app_url": "https://legacy.example.com/"}),
                encoding="utf-8",
            )

            from services.storage.json_storage import JSONStorageBackend

            backend = JSONStorageBackend(
                tmp_path / "accounts.json",
                tmp_path / "auth_keys.json",
                runtime_config_path,
            )
            store = self.config_module.ConfigStore(config_path, storage_backend=backend)

            self.assertEqual(store.public_app_url, "https://legacy.example.com")
            self.assertEqual(
                json.loads(runtime_config_path.read_text(encoding="utf-8")),
                {"public_app_url": "https://legacy.example.com/"},
            )

    def test_config_store_uses_json_storage_backend_for_runtime_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            from services.storage.json_storage import JSONStorageBackend

            backend = JSONStorageBackend(
                tmp_path / "accounts.json",
                tmp_path / "auth_keys.json",
                tmp_path / "runtime_config.json",
            )
            store = self.config_module.ConfigStore(tmp_path / "config.json", storage_backend=backend)
            store.update({"public_app_url": "https://json.example.com/"})

            reloaded_backend = JSONStorageBackend(
                tmp_path / "accounts.json",
                tmp_path / "auth_keys.json",
                tmp_path / "runtime_config.json",
            )
            reloaded = self.config_module.ConfigStore(tmp_path / "config.json", storage_backend=reloaded_backend)

            self.assertEqual(reloaded.public_app_url, "https://json.example.com")

    def test_config_store_uses_database_storage_backend_for_runtime_settings(self) -> None:
        try:
            from services.storage.database_storage import DatabaseStorageBackend
        except ImportError as exc:
            self.skipTest(f"database storage dependencies unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            database_url = f"sqlite:///{tmp_path / 'runtime.db'}"
            backend = DatabaseStorageBackend(database_url)
            store = self.config_module.ConfigStore(tmp_path / "config.json", storage_backend=backend)
            store.update({"public_app_url": "https://sqlite.example.com/"})

            reloaded = self.config_module.ConfigStore(
                tmp_path / "config.json",
                storage_backend=DatabaseStorageBackend(database_url),
            )

            self.assertEqual(reloaded.public_app_url, "https://sqlite.example.com")

    def test_service_runtime_settings_ignore_happytoken_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            module = self.config_module
            env_values = {
                "HAPPYTOKEN_BASE_URL": "https://env-base.example.com",
                "HAPPYTOKEN_FRONTEND_BASE_URL": "https://env.example.com",
                "HAPPYTOKEN_SESSION_SECRET": "env-session-secret",
                "HAPPYTOKEN_SESSION_COOKIE_NAME": "env_cookie",
                "HAPPYTOKEN_SESSION_MAX_AGE_SECONDS": "12345",
                "HAPPYTOKEN_SESSION_COOKIE_DOMAIN": "env.example.com",
                "HAPPYTOKEN_PROXY": "http://proxy.example.com",
                "HAPPYTOKEN_OIDC_ENABLED": "true",
                "HAPPYTOKEN_OIDC_ISSUER": "https://issuer.example.com",
                "HAPPYTOKEN_OIDC_CLIENT_ID": "env-client-id",
                "HAPPYTOKEN_OIDC_CLIENT_SECRET": "env-client-secret",
                "HAPPYTOKEN_OIDC_SCOPES": "openid email",
                "HAPPYTOKEN_OIDC_ALLOWED_EMAIL_DOMAINS": "example.com",
            }
            old_env = {key: module.os.environ.get(key) for key in env_values}
            try:
                module.os.environ.update(env_values)

                store = module.ConfigStore(Path(tmp_dir) / "config.json")

                self.assertEqual(store.base_url, "")
                self.assertEqual(store.session_secret, "")
                self.assertEqual(store.public_app_url, "")
                self.assertEqual(store.frontend_base_url, "")
                self.assertEqual(store.session_cookie_name, "happytoken_session")
                self.assertEqual(store.session_max_age_seconds, 86400)
                self.assertEqual(store.session_cookie_domain, "")
                self.assertEqual(store.get_proxy_settings(), "")
                self.assertEqual(
                    store.get_oidc_settings(),
                    {
                        "enabled": False,
                        "issuer": "",
                        "client_id": "",
                        "client_secret": "",
                        "scopes": "openid profile email",
                        "allowed_email_domains": "",
                    },
                )
            finally:
                for key, value in old_env.items():
                    if value is None:
                        module.os.environ.pop(key, None)
                    else:
                        module.os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
