import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient


class SetupAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)

    def make_client(self):
        from services import config as config_module
        from services.storage.json_storage import JSONStorageBackend
        from services.auth_service import AuthService
        import api.support as support_module
        import api.system as system_module
        import api.app as app_module

        storage = JSONStorageBackend(
            self.data_dir / "accounts.json",
            self.data_dir / "auth_keys.json",
            self.data_dir / "runtime_config.json",
        )
        test_config = config_module.ConfigStore(
            self.data_dir / "config.json", storage_backend=storage
        )
        test_auth = AuthService(storage)

        patches = [
            mock.patch.object(config_module, "config", test_config),
            mock.patch.object(support_module, "config", test_config),
            mock.patch.object(system_module, "config", test_config),
            mock.patch.object(system_module, "auth_service", test_auth),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        return TestClient(app_module.create_app())

    def test_setup_status_open_when_no_admin_exists(self) -> None:
        client = self.make_client()

        response = client.get("/api/setup/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["setup_required"], True)

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

        second = client.post(
            "/api/setup", json={"admin_name": "Other", "admin_key": "second-secret"}
        )
        self.assertEqual(second.status_code, 403)

    def test_admin_key_login_works_when_oidc_is_unavailable(self) -> None:
        client = self.make_client()
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


if __name__ == "__main__":
    unittest.main()
