import concurrent.futures
import multiprocessing
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient


def _create_first_admin_process_worker(
    barrier,
    queue,
    accounts_path: str,
    auth_keys_path: str,
    runtime_config_path: str,
    candidate: str,
) -> None:
    from services.storage.json_storage import JSONStorageBackend
    from services.auth_service import AuthService

    storage = JSONStorageBackend(
        Path(accounts_path),
        Path(auth_keys_path),
        Path(runtime_config_path),
    )
    auth = AuthService(storage)
    barrier.wait()
    try:
        item = auth.create_first_admin_with_value(
            name=f"Owner {candidate}",
            key=f"owner-secret-key-{candidate}",
        )
    except ValueError as exc:
        queue.put((False, str(exc)))
        return
    queue.put((True, str(item["id"])))


class SetupAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)

    def make_client(self, *, base_url: str = "http://testserver"):
        from services import config as config_module
        from services.storage.json_storage import JSONStorageBackend
        from services.auth_service import AuthService
        import api.support as support_module
        import api.system as system_module
        import api.app as app_module
        import services.web_session_service as web_session_module

        storage = JSONStorageBackend(
            self.data_dir / "accounts.json",
            self.data_dir / "auth_keys.json",
            self.data_dir / "runtime_config.json",
        )
        test_config = config_module.ConfigStore(
            self.data_dir / "config.json", storage_backend=storage
        )
        test_auth = AuthService(storage)
        self.test_config = test_config
        self.test_auth = test_auth
        system_module._AUTH_ATTEMPTS.clear()

        patches = [
            mock.patch.object(config_module, "config", test_config),
            mock.patch.object(support_module, "config", test_config),
            mock.patch.object(support_module, "auth_service", test_auth),
            mock.patch.object(system_module, "config", test_config),
            mock.patch.object(system_module, "auth_service", test_auth),
            mock.patch.object(web_session_module, "config", test_config),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        return TestClient(app_module.create_app(), base_url=base_url)

    def make_auth_service(self):
        from services.storage.json_storage import JSONStorageBackend
        from services.auth_service import AuthService

        storage = JSONStorageBackend(
            self.data_dir / "accounts.json",
            self.data_dir / "auth_keys.json",
            self.data_dir / "runtime_config.json",
        )
        return AuthService(storage)

    def test_create_first_admin_with_value_is_atomic(self) -> None:
        auth = self.make_auth_service()
        ready = threading.Barrier(2)

        def create(candidate: str) -> tuple[bool, str]:
            ready.wait()
            try:
                item = auth.create_first_admin_with_value(
                    name=f"Owner {candidate}",
                    key=f"owner-secret-key-{candidate}",
                )
            except ValueError as exc:
                return False, str(exc)
            return True, str(item["id"])

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create, ["one", "two"]))

        successes = [result for result in results if result[0]]
        failures = [result for result in results if not result[0]]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0][1], "初始化已完成")
        self.assertEqual(len(auth.list_keys("admin")), 1)

    def test_create_first_admin_is_atomic_across_auth_service_instances(self) -> None:
        from services.storage.json_storage import JSONStorageBackend
        from services.auth_service import AuthService

        storage_one = JSONStorageBackend(
            self.data_dir / "accounts.json",
            self.data_dir / "auth_keys.json",
            self.data_dir / "runtime_config.json",
        )
        storage_two = JSONStorageBackend(
            self.data_dir / "accounts.json",
            self.data_dir / "auth_keys.json",
            self.data_dir / "runtime_config.json",
        )
        auth_one = AuthService(storage_one)
        auth_two = AuthService(storage_two)
        ready = threading.Barrier(2)

        def create(auth: AuthService, candidate: str) -> tuple[bool, str]:
            ready.wait()
            try:
                item = auth.create_first_admin_with_value(
                    name=f"Owner {candidate}",
                    key=f"owner-secret-key-{candidate}",
                )
            except ValueError as exc:
                return False, str(exc)
            return True, str(item["id"])

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(create, auth_one, "one"),
                executor.submit(create, auth_two, "two"),
            ]
            results = [future.result() for future in futures]

        successes = [result for result in results if result[0]]
        failures = [result for result in results if not result[0]]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0][1], "初始化已完成")
        self.assertEqual(len(auth_one.list_keys("admin")), 1)
        self.assertEqual(len(auth_two.list_keys("admin")), 1)

    def test_create_first_admin_is_atomic_across_processes(self) -> None:
        try:
            context = multiprocessing.get_context("fork")
        except ValueError:
            self.skipTest("fork multiprocessing context is unavailable")
        accounts_path = self.data_dir / "accounts.json"
        auth_keys_path = self.data_dir / "auth_keys.json"
        runtime_config_path = self.data_dir / "runtime_config.json"
        barrier = context.Barrier(2)
        queue = context.Queue()
        processes = [
            context.Process(
                target=_create_first_admin_process_worker,
                args=(
                    barrier,
                    queue,
                    str(accounts_path),
                    str(auth_keys_path),
                    str(runtime_config_path),
                    candidate,
                ),
            )
            for candidate in ("one", "two")
        ]

        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=10)
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            self.assertEqual(process.exitcode, 0)

        results = [queue.get(timeout=1) for _ in processes]
        successes = [result for result in results if result[0]]
        failures = [result for result in results if not result[0]]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0][1], "初始化已完成")
        self.assertFalse(
            auth_keys_path.with_name(f"{auth_keys_path.name}.lock").exists()
        )

        auth = self.make_auth_service()
        self.assertEqual(len(auth.list_keys("admin")), 1)

    def test_git_first_admin_creation_is_atomic_across_instances(self) -> None:
        try:
            from git import Repo
            from services.auth_service import AuthService
            from services.storage.git_storage import GitStorageBackend
        except ImportError as exc:
            self.skipTest(f"git storage dependencies unavailable: {exc}")

        remote_path = self.data_dir / "remote.git"
        seed_path = self.data_dir / "seed"
        Repo.init(remote_path, bare=True)
        seed_repo = Repo.clone_from(str(remote_path), seed_path)
        (seed_path / "auth_keys.json").write_text('{"items": []}\n', encoding="utf-8")
        seed_repo.index.add(["auth_keys.json"])

        git_env = {
            "GIT_AUTHOR_NAME": "HappyImage Tests",
            "GIT_AUTHOR_EMAIL": "tests@example.com",
            "GIT_COMMITTER_NAME": "HappyImage Tests",
            "GIT_COMMITTER_EMAIL": "tests@example.com",
        }
        with mock.patch.dict(os.environ, git_env, clear=False):
            seed_repo.index.commit("Seed auth keys")
            seed_repo.git.branch("-M", "main")
            seed_repo.remote("origin").push("main")

            auth_one = AuthService(
                GitStorageBackend(
                    str(remote_path),
                    "",
                    branch="main",
                    local_cache_dir=self.data_dir / "cache-one",
                )
            )
            auth_two = AuthService(
                GitStorageBackend(
                    str(remote_path),
                    "",
                    branch="main",
                    local_cache_dir=self.data_dir / "cache-two",
                )
            )
            ready = threading.Barrier(2)

            def create(auth: AuthService, candidate: str) -> tuple[bool, str]:
                ready.wait()
                try:
                    item = auth.create_first_admin_with_value(
                        name=f"Owner {candidate}",
                        key=f"owner-secret-key-{candidate}",
                    )
                except ValueError as exc:
                    return False, str(exc)
                return True, str(item["id"])

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(create, auth_one, "one"),
                    executor.submit(create, auth_two, "two"),
                ]
                results = [future.result() for future in futures]

        successes = [result for result in results if result[0]]
        failures = [result for result in results if not result[0]]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0][1], "初始化已完成")
        self.assertEqual(len(auth_one.list_keys("admin")), 1)
        self.assertEqual(len(auth_two.list_keys("admin")), 1)

    def test_setup_status_open_when_no_admin_exists(self) -> None:
        client = self.make_client()

        response = client.get("/api/setup/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["setup_required"], True)
        self.assertIn("storage", response.json())
        storage = response.json()["storage"]
        self.assertEqual(storage["type"], "json")
        for key in (
            "file_path",
            "auth_keys_file_path",
            "runtime_config_file_path",
            "database_url",
            "repo_url",
        ):
            self.assertNotIn(key, storage)
        self.assertNotIn(str(self.data_dir), str(storage))

    def test_setup_creates_first_admin_and_settings(self) -> None:
        client = self.make_client()

        response = client.post(
            "/api/setup",
            json={
                "admin_name": "Owner",
                "admin_key": "owner-secret-key",
                "public_app_url": "https://image.example.com",
                "session_secret": "session-secret-with-at-least-32-characters",
                "oidc": {
                    "enabled": True,
                    "issuer": "https://auth.example.com",
                    "client_id": "happyimage",
                    "client_secret": "oidc-secret",
                    "scopes": "openid profile email",
                    "allowed_email_domains": "",
                },
                "model_gateway": {
                    "gateway_api_base_url": "https://gateway.happy-token.cn/v1",
                    "gateway_management_url": "",
                    "token_name": "HappyImage Default",
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["ok"], True)
        self.assertEqual(body["setup_required"], False)
        self.assertEqual(body["config"]["public_app_url"], "https://image.example.com")
        self.assertEqual(body["config"]["oidc"]["client_secret_configured"], True)
        self.assertEqual(body["admin"]["role"], "admin")

        status = client.get("/api/setup/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["setup_required"], False)
        self.assertNotIn("storage", status.json())

        second = client.post(
            "/api/setup", json={"admin_name": "Other", "admin_key": "second-secret"}
        )
        self.assertEqual(second.status_code, 403)

    def test_setup_post_is_rate_limited(self) -> None:
        client = self.make_client()

        responses = [
            client.post(
                "/api/setup",
                json={"admin_name": "Owner", "admin_key": "short"},
                headers={"X-Forwarded-For": f"203.0.113.{index}"},
            )
            for index in range(9)
        ]

        self.assertEqual(
            [response.status_code for response in responses[:8]], [400] * 8
        )
        self.assertEqual(responses[8].status_code, 429)

    def test_setup_rolls_back_first_admin_when_config_save_fails(self) -> None:
        client = self.make_client()

        with mock.patch.object(
            self.test_config, "update", side_effect=ValueError("config save failed")
        ):
            response = client.post(
                "/api/setup",
                json={
                    "admin_name": "Owner",
                    "admin_key": "owner-secret-key",
                    "public_app_url": "https://image.example.com",
                    "session_secret": "session-secret-with-at-least-32-characters",
                    "oidc": {"enabled": False},
                    "model_gateway": {
                        "gateway_api_base_url": "https://gateway.happy-token.cn/v1"
                    },
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.test_auth.list_keys("admin"), [])
        status = client.get("/api/setup/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["setup_required"], True)

    def test_setup_rejects_invalid_api_public_url(self) -> None:
        client = self.make_client()

        response = client.post(
            "/api/setup",
            json={
                "admin_name": "Owner",
                "admin_key": "owner-secret-key",
                "public_app_url": "https://image.example.com",
                "api_public_url": "ftp://api.example.com",
                "session_secret": "session-secret-with-at-least-32-characters",
                "oidc": {"enabled": False},
                "model_gateway": {
                    "gateway_api_base_url": "https://gateway.happy-token.cn/v1"
                },
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("http:// 或 https://", response.json()["detail"]["error"])
        self.assertEqual(self.test_auth.list_keys("admin"), [])

    def test_setup_rejects_bare_public_url_scheme(self) -> None:
        client = self.make_client()

        response = client.post(
            "/api/setup",
            json={
                "admin_name": "Owner",
                "admin_key": "owner-secret-key",
                "public_app_url": "https://",
                "session_secret": "session-secret-with-at-least-32-characters",
                "oidc": {"enabled": False},
                "model_gateway": {
                    "gateway_api_base_url": "https://gateway.happy-token.cn/v1"
                },
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("http:// 或 https://", response.json()["detail"]["error"])
        self.assertEqual(self.test_auth.list_keys("admin"), [])

    def test_setup_rejects_bare_api_public_url_scheme(self) -> None:
        client = self.make_client()

        response = client.post(
            "/api/setup",
            json={
                "admin_name": "Owner",
                "admin_key": "owner-secret-key",
                "public_app_url": "https://image.example.com",
                "api_public_url": "http://",
                "session_secret": "session-secret-with-at-least-32-characters",
                "oidc": {"enabled": False},
                "model_gateway": {
                    "gateway_api_base_url": "https://gateway.happy-token.cn/v1"
                },
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("http:// 或 https://", response.json()["detail"]["error"])
        self.assertEqual(self.test_auth.list_keys("admin"), [])

    def test_setup_rejects_bare_oidc_issuer_scheme(self) -> None:
        client = self.make_client()

        response = client.post(
            "/api/setup",
            json={
                "admin_name": "Owner",
                "admin_key": "owner-secret-key",
                "public_app_url": "https://image.example.com",
                "session_secret": "session-secret-with-at-least-32-characters",
                "oidc": {"enabled": True, "issuer": "https://"},
                "model_gateway": {
                    "gateway_api_base_url": "https://gateway.happy-token.cn/v1"
                },
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("http:// 或 https://", response.json()["detail"]["error"])
        self.assertEqual(self.test_auth.list_keys("admin"), [])

    def test_setup_rejects_invalid_gateway_url(self) -> None:
        client = self.make_client()

        response = client.post(
            "/api/setup",
            json={
                "admin_name": "Owner",
                "admin_key": "owner-secret-key",
                "public_app_url": "https://image.example.com",
                "session_secret": "session-secret-with-at-least-32-characters",
                "oidc": {"enabled": False},
                "model_gateway": {
                    "gateway_api_base_url": "javascript:alert(1)",
                },
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("http:// 或 https://", response.json()["detail"]["error"])
        self.assertEqual(self.test_auth.list_keys("admin"), [])

    def test_setup_rejects_bare_gateway_alias_urls(self) -> None:
        client = self.make_client()

        response = client.post(
            "/api/setup",
            json={
                "admin_name": "Owner",
                "admin_key": "owner-secret-key",
                "public_app_url": "https://image.example.com",
                "session_secret": "session-secret-with-at-least-32-characters",
                "oidc": {"enabled": False},
                "model_gateway": {
                    "base_url": "https://",
                    "management_url": "http://",
                },
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("http:// 或 https://", response.json()["detail"]["error"])
        self.assertEqual(self.test_auth.list_keys("admin"), [])

    def test_admin_key_login_works_when_oidc_is_unavailable(self) -> None:
        client = self.make_client(base_url="https://image.example.com")
        client.post(
            "/api/setup",
            json={
                "admin_name": "Owner",
                "admin_key": "owner-secret-key",
                "public_app_url": "https://image.example.com",
                "session_secret": "session-secret-with-at-least-32-characters",
                "oidc": {"enabled": False},
                "model_gateway": {
                    "gateway_api_base_url": "https://gateway.happy-token.cn/v1"
                },
            },
        )

        response = client.post(
            "/api/auth/admin-key-login",
            json={"key": "owner-secret-key"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], "admin")
        self.assertIn("httponly", response.headers.get("set-cookie", "").lower())

        settings_response = client.get("/api/settings")
        self.assertEqual(settings_response.status_code, 200)
        self.assertIn("config", settings_response.json())

    def test_admin_key_login_accepts_admin_key_field(self) -> None:
        client = self.make_client()
        setup_response = client.post(
            "/api/setup",
            json={
                "admin_name": "Owner",
                "admin_key": "owner-secret-key",
                "public_app_url": "https://image.example.com",
                "session_secret": "session-secret-with-at-least-32-characters",
                "oidc": {"enabled": False},
                "model_gateway": {
                    "gateway_api_base_url": "https://gateway.happy-token.cn/v1"
                },
            },
        )
        self.assertEqual(setup_response.status_code, 200)

        response = client.post(
            "/api/auth/admin-key-login",
            json={"admin_key": "owner-secret-key"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], "admin")

    def test_admin_key_login_rejects_invalid_key(self) -> None:
        client = self.make_client()
        setup_response = client.post(
            "/api/setup",
            json={
                "admin_name": "Owner",
                "admin_key": "owner-secret-key",
                "public_app_url": "https://image.example.com",
                "session_secret": "session-secret-with-at-least-32-characters",
                "oidc": {"enabled": False},
                "model_gateway": {
                    "gateway_api_base_url": "https://gateway.happy-token.cn/v1"
                },
            },
        )
        self.assertEqual(setup_response.status_code, 200)

        response = client.post(
            "/api/auth/admin-key-login",
            json={"key": "not-the-admin-key"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["error"], "管理员密钥无效")

    def test_admin_key_login_rate_limit_ignores_x_forwarded_for(self) -> None:
        client = self.make_client()
        setup_response = client.post(
            "/api/setup",
            json={
                "admin_name": "Owner",
                "admin_key": "owner-secret-key",
                "public_app_url": "https://image.example.com",
                "session_secret": "session-secret-with-at-least-32-characters",
                "oidc": {"enabled": False},
                "model_gateway": {
                    "gateway_api_base_url": "https://gateway.happy-token.cn/v1"
                },
            },
        )
        self.assertEqual(setup_response.status_code, 200)

        responses = [
            client.post(
                "/api/auth/admin-key-login",
                json={"key": "wrong-key"},
                headers={"X-Forwarded-For": f"203.0.113.{index}"},
            )
            for index in range(9)
        ]

        self.assertEqual(
            [response.status_code for response in responses[:8]], [401] * 8
        )
        self.assertEqual(responses[8].status_code, 429)


if __name__ == "__main__":
    unittest.main()
