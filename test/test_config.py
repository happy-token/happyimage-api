import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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

            def runtime_config_exists(self) -> bool:
                return bool(self.runtime_config)

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

    def test_update_restores_in_memory_config_when_runtime_save_fails(self) -> None:
        class FailingRuntimeStorage:
            def __init__(self) -> None:
                self.runtime_config: dict[str, object] = {
                    "public_app_url": "https://old.example.com"
                }

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

            def runtime_config_exists(self) -> bool:
                return True

            def save_runtime_config(self, config: dict[str, object]) -> None:
                raise RuntimeError("runtime save failed")

            def health_check(self) -> dict[str, object]:
                return {"status": "healthy"}

            def get_backend_info(self) -> dict[str, object]:
                return {"type": "memory"}

        store = self.config_module.ConfigStore(
            Path("ignored-config.json"), storage_backend=FailingRuntimeStorage()
        )

        with self.assertRaises(RuntimeError):
            store.update({"public_app_url": "https://new.example.com"})

        self.assertEqual(store.data, {"public_app_url": "https://old.example.com"})
        self.assertEqual(store.public_app_url, "https://old.example.com")

    def test_update_rejects_bare_oidc_issuer_scheme(self) -> None:
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

            def runtime_config_exists(self) -> bool:
                return bool(self.runtime_config)

            def save_runtime_config(self, config: dict[str, object]) -> None:
                self.runtime_config = dict(config)

            def health_check(self) -> dict[str, object]:
                return {"status": "healthy"}

            def get_backend_info(self) -> dict[str, object]:
                return {"type": "memory"}

        store = self.config_module.ConfigStore(
            Path("ignored-config.json"), storage_backend=MemoryStorage()
        )

        with self.assertRaises(ValueError):
            store.update({"oidc": {"enabled": True, "issuer": "https://"}})

        self.assertEqual(store.get_oidc_settings()["issuer"], "")

    def test_legacy_base_url_is_api_public_url_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"base_url": "https://legacy-api.example.com/"}),
                encoding="utf-8",
            )

            store = self.config_module.ConfigStore(config_path)

            self.assertEqual(store.api_public_url, "https://legacy-api.example.com")
            self.assertEqual(store.api_base_url, "https://legacy-api.example.com")
            self.assertEqual(store.external_api_url, "https://legacy-api.example.com")

    def test_legacy_newapi_binding_settings_are_model_gateway_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "newapi_binding": {
                            "base_url": "https://legacy-gateway.example.com/",
                            "management_url": "https://legacy-admin.example.com/",
                            "provision_url": "https://legacy-provision.example.com",
                            "provision_secret": "legacy-secret",
                            "sql_dsn": "sqlite:///legacy.db",
                            "token_name": "Legacy Token",
                        }
                    }
                ),
                encoding="utf-8",
            )

            store = self.config_module.ConfigStore(config_path)
            settings = store.get_model_gateway_settings()

            self.assertEqual(settings["gateway_api_base_url"], "https://legacy-gateway.example.com/v1")
            self.assertEqual(settings["gateway_management_url"], "https://legacy-admin.example.com")
            self.assertEqual(settings["base_url"], "https://legacy-gateway.example.com/v1")
            self.assertEqual(settings["management_url"], "https://legacy-admin.example.com")
            self.assertEqual(settings["provision_url"], "https://legacy-provision.example.com")
            self.assertEqual(settings["provision_secret"], "legacy-secret")
            self.assertTrue(settings["provision_secret_configured"])
            self.assertEqual(settings["sql_dsn"], "sqlite:///legacy.db")
            self.assertTrue(settings["sql_dsn_configured"])
            self.assertEqual(settings["token_name"], "Legacy Token")
            self.assertTrue(settings["enabled"])

    def test_public_config_redacts_model_gateway_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "model_gateway": {
                            "gateway_api_base_url": "https://gateway.example.com/",
                            "gateway_management_url": "",
                            "provision_url": "https://provision.example.com",
                            "provision_secret": "super-secret",
                            "sql_dsn": "postgresql://user:secret@db/new-api",
                            "token_name": "Secret Token",
                        }
                    }
                ),
                encoding="utf-8",
            )

            response = self.config_module.ConfigStore(config_path).get()
            model_gateway = response["model_gateway"]

            self.assertNotIn("provision_secret", model_gateway)
            self.assertNotIn("sql_dsn", model_gateway)
            self.assertTrue(model_gateway["provision_secret_configured"])
            self.assertTrue(model_gateway["sql_dsn_configured"])
            self.assertEqual(model_gateway["gateway_api_base_url"], "https://gateway.example.com/v1")
            self.assertEqual(model_gateway["gateway_management_url"], "https://gateway.example.com")

    def test_public_config_redacts_ai_review_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "ai_review": {
                            "enabled": True,
                            "base_url": "https://review.example.com/v1",
                            "api_key": "review-secret",
                            "model": "moderation-model",
                        }
                    }
                ),
                encoding="utf-8",
            )

            response = self.config_module.ConfigStore(config_path).get()
            ai_review = response["ai_review"]

            self.assertNotIn("api_key", ai_review)
            self.assertTrue(ai_review["api_key_configured"])
            self.assertEqual(ai_review["base_url"], "https://review.example.com/v1")
            self.assertEqual(ai_review["model"], "moderation-model")

    def test_public_config_redacts_image_storage_webdav_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "image_storage": {
                            "enabled": True,
                            "mode": "webdav",
                            "webdav_url": "https://dav.example.com/",
                            "webdav_username": "image-user",
                            "webdav_password": "webdav-secret",
                            "webdav_root_path": "/images/",
                            "public_base_url": "https://cdn.example.com/",
                        }
                    }
                ),
                encoding="utf-8",
            )

            response = self.config_module.ConfigStore(config_path).get()
            image_storage = response["image_storage"]

            self.assertNotIn("webdav_password", image_storage)
            self.assertTrue(image_storage["webdav_password_configured"])
            self.assertEqual(image_storage["webdav_url"], "https://dav.example.com")
            self.assertEqual(image_storage["webdav_username"], "image-user")
            self.assertEqual(image_storage["webdav_root_path"], "images")
            self.assertEqual(image_storage["public_base_url"], "https://cdn.example.com")

    def test_public_config_does_not_expose_legacy_newapi_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "newapi_binding": {
                            "base_url": "https://legacy-gateway.example.com/",
                            "provision_secret": "legacy-secret",
                            "sql_dsn": "sqlite:///legacy.db",
                        }
                    }
                ),
                encoding="utf-8",
            )

            response = self.config_module.ConfigStore(config_path).get()
            model_gateway = response["model_gateway"]

            self.assertNotIn("newapi_binding", response)
            self.assertNotIn("provision_secret", model_gateway)
            self.assertNotIn("sql_dsn", model_gateway)
            self.assertTrue(model_gateway["provision_secret_configured"])
            self.assertTrue(model_gateway["sql_dsn_configured"])

    def test_model_gateway_update_preserves_existing_redacted_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "model_gateway": {
                            "gateway_api_base_url": "https://old-gateway.example.com/v1",
                            "gateway_management_url": "https://old-admin.example.com",
                            "provision_url": "https://old-provision.example.com",
                            "provision_secret": "stored-secret",
                            "sql_dsn": "postgresql://stored:secret@db/new-api",
                            "token_name": "Old Token",
                        }
                    }
                ),
                encoding="utf-8",
            )

            store = self.config_module.ConfigStore(config_path)
            response = store.update(
                {
                    "model_gateway": {
                        "gateway_api_base_url": "https://new-gateway.example.com/",
                        "gateway_management_url": "",
                        "provision_url": "https://new-provision.example.com",
                        "provision_secret": "",
                        "provision_secret_configured": True,
                        "sql_dsn_configured": True,
                        "token_name": "New Token",
                    }
                }
            )

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            saved_gateway = saved["model_gateway"]
            response_gateway = response["model_gateway"]
            self.assertEqual(saved_gateway["gateway_api_base_url"], "https://new-gateway.example.com/v1")
            self.assertEqual(saved_gateway["gateway_management_url"], "https://new-gateway.example.com")
            self.assertEqual(saved_gateway["provision_url"], "https://new-provision.example.com")
            self.assertEqual(saved_gateway["provision_secret"], "stored-secret")
            self.assertEqual(saved_gateway["sql_dsn"], "postgresql://stored:secret@db/new-api")
            self.assertEqual(saved_gateway["token_name"], "New Token")
            self.assertNotIn("provision_secret", response_gateway)
            self.assertNotIn("sql_dsn", response_gateway)
            self.assertTrue(response_gateway["provision_secret_configured"])
            self.assertTrue(response_gateway["sql_dsn_configured"])

    def test_update_preserves_existing_redacted_ai_review_and_image_storage_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "ai_review": {
                            "enabled": True,
                            "base_url": "https://old-review.example.com/v1",
                            "api_key": "stored-review-key",
                            "model": "old-review-model",
                        },
                        "image_storage": {
                            "enabled": True,
                            "mode": "webdav",
                            "webdav_url": "https://old-dav.example.com",
                            "webdav_username": "old-image-user",
                            "webdav_password": "stored-webdav-password",
                            "webdav_root_path": "old-images",
                            "public_base_url": "https://old-cdn.example.com",
                        },
                    }
                ),
                encoding="utf-8",
            )

            store = self.config_module.ConfigStore(config_path)
            response = store.update(
                {
                    "ai_review": {
                        "enabled": True,
                        "base_url": "https://new-review.example.com/v1",
                        "api_key": "",
                        "api_key_configured": True,
                        "model": "new-review-model",
                    },
                    "image_storage": {
                        "enabled": True,
                        "mode": "webdav",
                        "webdav_url": "https://new-dav.example.com/",
                        "webdav_username": "new-image-user",
                        "webdav_password": "",
                        "webdav_password_configured": True,
                        "webdav_root_path": "/new-images/",
                        "public_base_url": "https://new-cdn.example.com/",
                    },
                }
            )

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            saved_ai_review = saved["ai_review"]
            saved_image_storage = saved["image_storage"]
            response_ai_review = response["ai_review"]
            response_image_storage = response["image_storage"]
            self.assertEqual(saved_ai_review["base_url"], "https://new-review.example.com/v1")
            self.assertEqual(saved_ai_review["api_key"], "stored-review-key")
            self.assertEqual(saved_ai_review["model"], "new-review-model")
            self.assertEqual(saved_image_storage["webdav_url"], "https://new-dav.example.com")
            self.assertEqual(saved_image_storage["webdav_username"], "new-image-user")
            self.assertEqual(saved_image_storage["webdav_password"], "stored-webdav-password")
            self.assertEqual(saved_image_storage["webdav_root_path"], "new-images")
            self.assertEqual(saved_image_storage["public_base_url"], "https://new-cdn.example.com")
            self.assertNotIn("api_key", response_ai_review)
            self.assertTrue(response_ai_review["api_key_configured"])
            self.assertNotIn("webdav_password", response_image_storage)
            self.assertTrue(response_image_storage["webdav_password_configured"])

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

    def test_empty_runtime_config_does_not_resurrect_legacy_file(self) -> None:
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
            backend.save_runtime_config({})

            reloaded_backend = JSONStorageBackend(
                tmp_path / "accounts.json",
                tmp_path / "auth_keys.json",
                runtime_config_path,
            )
            store = self.config_module.ConfigStore(config_path, storage_backend=reloaded_backend)

            self.assertEqual(store.data, {})
            self.assertEqual(store.public_app_url, "")
            self.assertEqual(json.loads(runtime_config_path.read_text(encoding="utf-8")), {})

    def test_malformed_json_runtime_config_raises_instead_of_loading_empty_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runtime_config_path = tmp_path / "runtime_config.json"
            runtime_config_path.write_text("{not valid json", encoding="utf-8")

            from services.storage.json_storage import JSONStorageBackend

            backend = JSONStorageBackend(
                tmp_path / "accounts.json",
                tmp_path / "auth_keys.json",
                runtime_config_path,
            )

            with self.assertRaises(json.JSONDecodeError):
                self.config_module.ConfigStore(tmp_path / "config.json", storage_backend=backend)

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

    def test_json_runtime_config_save_failure_does_not_corrupt_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            from services.storage.json_storage import JSONStorageBackend
            import services.storage.json_storage as json_storage_module

            runtime_config_path = tmp_path / "runtime_config.json"
            backend = JSONStorageBackend(
                tmp_path / "accounts.json",
                tmp_path / "auth_keys.json",
                runtime_config_path,
            )
            backend.save_runtime_config({"public_app_url": "https://old.example.com"})

            with mock.patch.object(
                json_storage_module.os,
                "replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaises(OSError):
                    backend.save_runtime_config(
                        {"public_app_url": "https://new.example.com"}
                    )

            self.assertEqual(
                json.loads(runtime_config_path.read_text(encoding="utf-8")),
                {"public_app_url": "https://old.example.com"},
            )

    def test_git_runtime_config_push_rejection_raises_and_rolls_back_store(self) -> None:
        try:
            from git import Repo
            from git.exc import GitCommandError
            from services.storage.git_storage import GitStorageBackend
        except ImportError as exc:
            self.skipTest(f"git storage dependencies unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                old_cwd = os.getcwd()
            except FileNotFoundError:
                old_cwd = str(ROOT_DIR)
            os.chdir(ROOT_DIR)
            tmp_path = Path(tmp_dir)
            remote_path = tmp_path / "remote.git"
            seed_path = tmp_path / "seed"
            try:
                Repo.init(remote_path, bare=True)
                seed_repo = Repo.clone_from(str(remote_path), seed_path)
                (seed_path / "runtime_config.json").write_text(
                    json.dumps({"public_app_url": "https://old.example.com"}) + "\n",
                    encoding="utf-8",
                )
                seed_repo.index.add(["runtime_config.json"])

                git_env = {
                    "GIT_AUTHOR_NAME": "HappyImage Tests",
                    "GIT_AUTHOR_EMAIL": "tests@example.com",
                    "GIT_COMMITTER_NAME": "HappyImage Tests",
                    "GIT_COMMITTER_EMAIL": "tests@example.com",
                }
                with mock.patch.dict(os.environ, git_env, clear=False):
                    seed_repo.index.commit("Seed runtime config")
                    seed_repo.git.branch("-M", "main")
                    seed_repo.remote("origin").push("main")

                    backend = GitStorageBackend(
                        str(remote_path),
                        "",
                        branch="main",
                        local_cache_dir=tmp_path / "cache",
                    )
                    store = self.config_module.ConfigStore(
                        tmp_path / "config.json", storage_backend=backend
                    )

                    with mock.patch.object(
                        backend,
                        "_push_or_raise",
                        side_effect=GitCommandError("git push", "rejected"),
                    ):
                        with self.assertRaises(GitCommandError):
                            store.update({"public_app_url": "https://new.example.com"})
            finally:
                os.chdir(old_cwd if Path(old_cwd).exists() else ROOT_DIR)

            self.assertEqual(store.public_app_url, "https://old.example.com")
            self.assertEqual(
                store.data, {"public_app_url": "https://old.example.com"}
            )

    def test_git_push_result_failure_flags_include_remote_failure_and_no_match(self) -> None:
        try:
            from services.storage.git_storage import GitStorageBackend
        except ImportError as exc:
            self.skipTest(f"git storage dependencies unavailable: {exc}")

        class FakePushResult:
            ERROR = 1
            REJECTED = 2
            REMOTE_REJECTED = 4
            REMOTE_FAILURE = 8
            NO_MATCH = 16

            def __init__(self, flags: int) -> None:
                self.flags = flags

        self.assertTrue(
            GitStorageBackend._push_result_failed(
                FakePushResult(FakePushResult.REMOTE_FAILURE)
            )
        )
        self.assertTrue(
            GitStorageBackend._push_result_failed(
                FakePushResult(FakePushResult.NO_MATCH)
            )
        )
        self.assertFalse(GitStorageBackend._push_result_failed(FakePushResult(0)))

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

    def test_malformed_database_runtime_config_raises_instead_of_loading_empty_config(self) -> None:
        try:
            from services.storage.database_storage import DatabaseStorageBackend, RuntimeConfigModel
        except ImportError as exc:
            self.skipTest(f"database storage dependencies unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'runtime.db'}")
            session = backend.Session()
            try:
                session.add(RuntimeConfigModel(key="default", data="{not valid json"))
                session.commit()
            finally:
                session.close()

            with self.assertRaises(json.JSONDecodeError):
                self.config_module.ConfigStore(tmp_path / "config.json", storage_backend=backend)

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
