# OIDC Login and Frontend/Backend Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add generic OIDC web login for HappyImage users and split the product into required frontend and backend services while preserving Bearer-token API compatibility.

**Architecture:** The backend owns OIDC protocol handling, signed web sessions, Cookie auth for `/api/*`, and Bearer auth for `/v1/*`. The frontend becomes a separate service that calls the backend through `NEXT_PUBLIC_API_BASE_URL` with credentials enabled. Existing user key and quota records remain the canonical HappyImage user model.

**Tech Stack:** FastAPI, Pydantic, curl_cffi, PyJWT with crypto support for OIDC ID token verification, Next.js static export, Axios, Docker Compose, pytest.

---

## File Structure

- Create `services/oidc_config.py`: normalize OIDC/session/frontend config and secret redaction.
- Create `services/web_session_service.py`: sign, verify, set, and clear HappyImage web session cookies.
- Create `services/oidc_service.py`: OIDC discovery, authorize URL generation, callback token exchange, ID token validation, userinfo loading, domain allowlist enforcement, and user binding.
- Create `api/auth.py`: new auth routes for web session, logout, OIDC start, and OIDC callback.
- Modify `api/support.py`: add cookie-aware `/api/*` auth helpers while leaving Bearer-only helpers for `/v1/*`.
- Modify `api/app.py`: wire the new auth router and credentialed CORS configuration.
- Modify `services/config.py`: expose normalized OIDC/session/frontend config and settings redaction.
- Modify `services/auth_service.py`: preserve OIDC metadata on auth key records and add lookup helpers by provider subject/email.
- Modify `services/storage/*` only if tests reveal metadata is lost; current JSON/database storage stores whole item data and should not need schema changes.
- Modify `api/system.py`: remove or delegate duplicated login/session behavior only where necessary; keep settings endpoints.
- Modify `web/src/constants/common-env.ts`: read `NEXT_PUBLIC_API_BASE_URL` in every environment.
- Modify `web/src/lib/request.ts`: set `withCredentials: true` and keep Bearer injection only when a local access key exists.
- Modify `web/src/lib/api.ts`: add OIDC/session/logout/config-status API functions.
- Modify `web/src/lib/auth-session.ts`: validate sessions through `GET /api/auth/session` instead of re-posting the stored access key.
- Modify `web/src/store/auth.ts`: support cookie-backed sessions without requiring a JS-readable key.
- Modify `web/src/app/login/page.tsx`: show local admin/access-key login plus OIDC login when enabled.
- Modify `web/src/app/settings/page.tsx` and create `web/src/app/settings/components/oidc-settings-card.tsx`: add admin-configurable OIDC settings with secret redaction.
- Modify `Dockerfile`: split backend and frontend build targets.
- Modify `docker-compose.yml` and `docker-compose.local.yml`: run `happyimage-api` and `happyimage-web` as separate services.
- Modify `README.md`, `docs/docker-deployment.md`, and `config.example.json`: document separated deployment and OIDC config.

## Task 1: Normalize OIDC, Session, and Split-Service Config

**Files:**
- Create: `services/oidc_config.py`
- Modify: `services/config.py`
- Modify: `config.example.json`
- Test: `test/test_oidc_config.py`

- [ ] **Step 1: Write failing config tests**

Create `test/test_oidc_config.py`:

```python
import os

from services.oidc_config import OIDCSettings, redact_oidc_settings


def test_oidc_settings_from_mapping_defaults_to_disabled():
    settings = OIDCSettings.from_mapping({})

    assert settings.enabled is False
    assert settings.scopes == "openid profile email"
    assert settings.allowed_email_domains == []
    assert settings.default_image_quota == 0


def test_oidc_settings_normalizes_domains_and_quota():
    settings = OIDCSettings.from_mapping({
        "oidc_enabled": "true",
        "oidc_allowed_email_domains": " Example.COM, team.example.com ,,",
        "oidc_default_image_quota": "12",
    })

    assert settings.enabled is True
    assert settings.allowed_email_domains == ["example.com", "team.example.com"]
    assert settings.default_image_quota == 12


def test_oidc_settings_environment_overrides_mapping(monkeypatch):
    monkeypatch.setenv("HAPPYIMAGE_OIDC_ENABLED", "true")
    monkeypatch.setenv("HAPPYIMAGE_OIDC_ISSUER", "https://idp.example.com")
    monkeypatch.setenv("HAPPYIMAGE_OIDC_CLIENT_ID", "web-client")
    monkeypatch.setenv("HAPPYIMAGE_OIDC_CLIENT_SECRET", "secret-value")

    settings = OIDCSettings.from_mapping({
        "oidc_enabled": False,
        "oidc_issuer": "https://ignored.example.com",
        "oidc_client_id": "ignored",
        "oidc_client_secret": "ignored",
    }, environ=os.environ)

    assert settings.enabled is True
    assert settings.issuer == "https://idp.example.com"
    assert settings.client_id == "web-client"
    assert settings.client_secret == "secret-value"


def test_redacted_settings_do_not_expose_secret():
    settings = OIDCSettings.from_mapping({
        "oidc_enabled": True,
        "oidc_issuer": "https://idp.example.com",
        "oidc_client_id": "web-client",
        "oidc_client_secret": "secret-value",
    })

    redacted = redact_oidc_settings(settings)

    assert redacted["client_secret"] == ""
    assert redacted["has_client_secret"] is True
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `uv run pytest test/test_oidc_config.py -q`

Expected: fails with `ModuleNotFoundError: No module named 'services.oidc_config'`.

- [ ] **Step 3: Implement config dataclasses**

Create `services/oidc_config.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


def _clean(value: object) -> str:
    return str(value or "").strip()


def _bool(value: object, default: bool = False) -> bool:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _int(value: object, default: int, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _env(environ: Mapping[str, str] | None, key: str) -> str:
    return _clean((environ or {}).get(key))


def _domains(value: object) -> list[str]:
    if isinstance(value, list):
        parts = value
    else:
        parts = _clean(value).split(",")
    return [domain.strip().lower().lstrip("@") for domain in parts if str(domain).strip()]


@dataclass(frozen=True)
class OIDCSettings:
    enabled: bool
    issuer: str
    client_id: str
    client_secret: str
    scopes: str
    allowed_email_domains: list[str]
    default_image_quota: int

    @classmethod
    def from_mapping(cls, data: Mapping[str, object], environ: Mapping[str, str] | None = None) -> "OIDCSettings":
        return cls(
            enabled=_bool(_env(environ, "HAPPYIMAGE_OIDC_ENABLED") or data.get("oidc_enabled"), False),
            issuer=_clean(_env(environ, "HAPPYIMAGE_OIDC_ISSUER") or data.get("oidc_issuer")),
            client_id=_clean(_env(environ, "HAPPYIMAGE_OIDC_CLIENT_ID") or data.get("oidc_client_id")),
            client_secret=_clean(_env(environ, "HAPPYIMAGE_OIDC_CLIENT_SECRET") or data.get("oidc_client_secret")),
            scopes=_clean(_env(environ, "HAPPYIMAGE_OIDC_SCOPES") or data.get("oidc_scopes") or "openid profile email"),
            allowed_email_domains=_domains(
                _env(environ, "HAPPYIMAGE_OIDC_ALLOWED_EMAIL_DOMAINS")
                or data.get("oidc_allowed_email_domains")
            ),
            default_image_quota=_int(
                _env(environ, "HAPPYIMAGE_OIDC_DEFAULT_IMAGE_QUOTA")
                or data.get("oidc_default_image_quota"),
                0,
                0,
            ),
        )


@dataclass(frozen=True)
class WebSessionSettings:
    frontend_base_url: str
    api_base_url: str
    cors_origins: list[str]
    session_secret: str
    session_cookie_name: str
    session_max_age_seconds: int
    secure_cookies: bool

    @classmethod
    def from_mapping(cls, data: Mapping[str, object], environ: Mapping[str, str] | None = None) -> "WebSessionSettings":
        frontend = _clean(_env(environ, "HAPPYIMAGE_FRONTEND_BASE_URL") or data.get("frontend_base_url"))
        cors_raw = _env(environ, "HAPPYIMAGE_CORS_ORIGINS") or data.get("cors_origins") or frontend
        cors = [origin.strip().rstrip("/") for origin in _clean(cors_raw).split(",") if origin.strip()]
        return cls(
            frontend_base_url=frontend.rstrip("/"),
            api_base_url=_clean(_env(environ, "HAPPYIMAGE_API_BASE_URL") or data.get("api_base_url")).rstrip("/"),
            cors_origins=cors,
            session_secret=_clean(_env(environ, "HAPPYIMAGE_SESSION_SECRET") or data.get("session_secret")),
            session_cookie_name=_clean(
                _env(environ, "HAPPYIMAGE_SESSION_COOKIE_NAME")
                or data.get("session_cookie_name")
                or "happyimage_session"
            ),
            session_max_age_seconds=_int(
                _env(environ, "HAPPYIMAGE_SESSION_MAX_AGE_SECONDS")
                or data.get("session_max_age_seconds"),
                60 * 60 * 24 * 7,
                60,
            ),
            secure_cookies=_bool(_env(environ, "HAPPYIMAGE_SECURE_COOKIES") or data.get("secure_cookies"), True),
        )


def redact_oidc_settings(settings: OIDCSettings) -> dict[str, object]:
    return {
        "enabled": settings.enabled,
        "issuer": settings.issuer,
        "client_id": settings.client_id,
        "client_secret": "",
        "has_client_secret": bool(settings.client_secret),
        "scopes": settings.scopes,
        "allowed_email_domains": settings.allowed_email_domains,
        "default_image_quota": settings.default_image_quota,
    }
```

- [ ] **Step 4: Wire config store accessors**

Modify `services/config.py` imports:

```python
from services.oidc_config import OIDCSettings, WebSessionSettings, redact_oidc_settings
```

Add methods to `ConfigStore`:

```python
    @property
    def oidc_settings(self) -> OIDCSettings:
        return OIDCSettings.from_mapping(self.data, os.environ)

    @property
    def web_session_settings(self) -> WebSessionSettings:
        return WebSessionSettings.from_mapping(self.data, os.environ)

    def get_oidc_settings_public(self) -> dict[str, object]:
        return redact_oidc_settings(self.oidc_settings)
```

In `ConfigStore.get()`, include redacted OIDC settings and non-secret session settings:

```python
        data["oidc"] = self.get_oidc_settings_public()
        web_session = self.web_session_settings
        data["frontend_base_url"] = web_session.frontend_base_url
        data["api_base_url"] = web_session.api_base_url
        data["cors_origins"] = ",".join(web_session.cors_origins)
        data["session_cookie_name"] = web_session.session_cookie_name
        data["session_max_age_seconds"] = web_session.session_max_age_seconds
```

In `ConfigStore.update()`, preserve an existing OIDC secret when the incoming value is empty:

```python
        if "oidc_client_secret" in updates and not str(updates.get("oidc_client_secret") or "").strip():
            updates.pop("oidc_client_secret", None)
```

Place that snippet before `self.data.update(updates)`.

- [ ] **Step 5: Update example config**

Modify `config.example.json` to include:

```json
  "frontend_base_url": "http://127.0.0.1:3000",
  "api_base_url": "http://127.0.0.1:8000",
  "cors_origins": "http://127.0.0.1:3000",
  "session_secret": "replace_with_a_long_random_session_secret",
  "session_cookie_name": "happyimage_session",
  "session_max_age_seconds": 604800,
  "secure_cookies": false,
  "oidc_enabled": false,
  "oidc_issuer": "",
  "oidc_client_id": "",
  "oidc_client_secret": "",
  "oidc_scopes": "openid profile email",
  "oidc_allowed_email_domains": "",
  "oidc_default_image_quota": 0
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest test/test_oidc_config.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add services/oidc_config.py services/config.py config.example.json test/test_oidc_config.py
git commit -m "feat: add oidc session configuration"
```

## Task 2: Preserve OIDC Metadata in Auth Users

**Files:**
- Modify: `services/auth_service.py`
- Test: `test/test_oidc_auth_service.py`

- [ ] **Step 1: Write failing auth metadata tests**

Create `test/test_oidc_auth_service.py`:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from services.auth_service import AuthService
from services.storage.json_storage import JSONStorageBackend


def make_service(tmp_dir: str) -> AuthService:
    return AuthService(JSONStorageBackend(Path(tmp_dir) / "accounts.json", Path(tmp_dir) / "auth_keys.json"))


def test_create_oidc_user_preserves_provider_metadata():
    with TemporaryDirectory() as tmp_dir:
        service = make_service(tmp_dir)

        item = service.create_oidc_user(
            provider="oidc",
            subject="sub-123",
            email="alice@example.com",
            name="Alice",
            image_quota=0,
        )

        assert item["role"] == "user"
        assert item["auth_provider"] == "oidc"
        assert item["auth_subject"] == "sub-123"
        assert item["email"] == "alice@example.com"
        assert item["image_quota"] == 0


def test_find_by_oidc_subject_returns_existing_user():
    with TemporaryDirectory() as tmp_dir:
        service = make_service(tmp_dir)
        created = service.create_oidc_user(
            provider="oidc",
            subject="sub-123",
            email="alice@example.com",
            name="Alice",
            image_quota=0,
        )

        found = service.find_by_auth_binding("oidc", "sub-123")

        assert found is not None
        assert found["id"] == created["id"]


def test_same_email_conflict_is_detected_for_unbound_local_user():
    with TemporaryDirectory() as tmp_dir:
        service = make_service(tmp_dir)
        service.create_key_with_value(role="user", name="alice@example.com", key="alice-password", image_quota=5)

        conflict = service.find_email_conflict("alice@example.com", provider="oidc", subject="sub-123")

        assert conflict is not None
        assert conflict["name"] == "alice@example.com"
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `uv run pytest test/test_oidc_auth_service.py -q`

Expected: fails because `create_oidc_user`, `find_by_auth_binding`, and `find_email_conflict` do not exist.

- [ ] **Step 3: Extend public item shape**

Modify `AuthService._public_item()` in `services/auth_service.py`:

```python
    @staticmethod
    def _public_item(item: dict[str, object]) -> dict[str, object]:
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "role": item.get("role"),
            "enabled": bool(item.get("enabled", True)),
            "image_quota": item.get("image_quota"),
            "created_at": item.get("created_at"),
            "last_used_at": item.get("last_used_at"),
            "auth_provider": item.get("auth_provider"),
            "auth_subject": item.get("auth_subject"),
            "email": item.get("email"),
            "external_name": item.get("external_name"),
        }
```

- [ ] **Step 4: Preserve metadata during normalization**

In `_normalize_item()`, add normalized metadata to the returned dict:

```python
        auth_provider = self._clean(raw.get("auth_provider")).lower()
        auth_subject = self._clean(raw.get("auth_subject"))
        email = self._clean(raw.get("email")).lower()
        external_name = self._clean(raw.get("external_name"))
```

Add these keys to the returned item:

```python
            "auth_provider": auth_provider or None,
            "auth_subject": auth_subject or None,
            "email": email or None,
            "external_name": external_name or None,
```

- [ ] **Step 5: Add OIDC lookup and creation methods**

Add methods to `AuthService`:

```python
    def find_by_auth_binding(self, provider: str, subject: str) -> dict[str, object] | None:
        normalized_provider = self._clean(provider).lower()
        normalized_subject = self._clean(subject)
        if not normalized_provider or not normalized_subject:
            return None
        with self._lock:
            self._reload_locked()
            for item in self._items:
                if self._clean(item.get("auth_provider")).lower() != normalized_provider:
                    continue
                if self._clean(item.get("auth_subject")) != normalized_subject:
                    continue
                return self._public_item(item)
        return None

    def find_email_conflict(self, email: str, *, provider: str, subject: str) -> dict[str, object] | None:
        normalized_email = self._clean(email).lower()
        normalized_provider = self._clean(provider).lower()
        normalized_subject = self._clean(subject)
        if not normalized_email:
            return None
        with self._lock:
            self._reload_locked()
            for item in self._items:
                if self._clean(item.get("email")).lower() != normalized_email and self._clean(item.get("name")).lower() != normalized_email:
                    continue
                same_binding = (
                    self._clean(item.get("auth_provider")).lower() == normalized_provider
                    and self._clean(item.get("auth_subject")) == normalized_subject
                )
                if not same_binding:
                    return self._public_item(item)
        return None

    def create_oidc_user(
        self,
        *,
        provider: str,
        subject: str,
        email: str,
        name: str,
        image_quota: object = 0,
    ) -> dict[str, object]:
        normalized_provider = self._clean(provider).lower()
        normalized_subject = self._clean(subject)
        normalized_email = self._clean(email).lower()
        display_name = self._clean(name) or normalized_email or "OIDC 用户"
        if not normalized_provider or not normalized_subject:
            raise ValueError("OIDC 用户缺少 provider 或 subject")
        with self._lock:
            self._reload_locked()
            for item in self._items:
                if self._clean(item.get("auth_provider")).lower() == normalized_provider and self._clean(item.get("auth_subject")) == normalized_subject:
                    return self._public_item(item)
            key_hash = _hash_key(f"oidc:{normalized_provider}:{normalized_subject}:{secrets.token_urlsafe(24)}")
            item = {
                "id": uuid.uuid4().hex[:12],
                "name": self._build_name_locked(display_name, role="user"),
                "role": "user",
                "key_hash": key_hash,
                "enabled": True,
                "image_quota": self._normalize_image_quota(image_quota),
                "created_at": _now_iso(),
                "last_used_at": None,
                "auth_provider": normalized_provider,
                "auth_subject": normalized_subject,
                "email": normalized_email or None,
                "external_name": display_name,
            }
            self._items.append(item)
            self._save()
            return self._public_item(item)
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest test/test_oidc_auth_service.py test/test_account_image_capabilities.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add services/auth_service.py test/test_oidc_auth_service.py
git commit -m "feat: preserve oidc user bindings"
```

## Task 3: Add Signed Web Session Service

**Files:**
- Create: `services/web_session_service.py`
- Test: `test/test_web_session_service.py`

- [ ] **Step 1: Write failing web session tests**

Create `test/test_web_session_service.py`:

```python
from services.oidc_config import WebSessionSettings
from services.web_session_service import WebSessionService


def make_service() -> WebSessionService:
    settings = WebSessionSettings.from_mapping({
        "frontend_base_url": "http://127.0.0.1:3000",
        "api_base_url": "http://127.0.0.1:8000",
        "session_secret": "test-secret-with-enough-length",
        "session_cookie_name": "happyimage_session",
        "session_max_age_seconds": 3600,
        "secure_cookies": False,
    })
    return WebSessionService(settings)


def test_round_trip_session_token():
    service = make_service()

    token = service.create_token({"id": "u1", "role": "user", "name": "Alice"})
    identity = service.verify_token(token)

    assert identity["id"] == "u1"
    assert identity["role"] == "user"
    assert identity["name"] == "Alice"


def test_tampered_session_token_is_rejected():
    service = make_service()

    token = service.create_token({"id": "u1", "role": "user", "name": "Alice"})
    bad_token = token[:-2] + "xx"

    assert service.verify_token(bad_token) is None
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `uv run pytest test/test_web_session_service.py -q`

Expected: fails with `ModuleNotFoundError: No module named 'services.web_session_service'`.

- [ ] **Step 3: Implement signed session service**

Create `services/web_session_service.py`:

```python
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import Response

from services.config import config
from services.oidc_config import WebSessionSettings


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


class WebSessionService:
    def __init__(self, settings: WebSessionSettings):
        self.settings = settings

    def _signature(self, payload: str) -> str:
        digest = hmac.new(
            self.settings.session_secret.encode("utf-8"),
            payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return _b64encode(digest)

    def create_token(self, identity: dict[str, Any]) -> str:
        now = int(time.time())
        payload = {
            "id": str(identity.get("id") or ""),
            "role": str(identity.get("role") or "user"),
            "name": str(identity.get("name") or ""),
            "image_quota": identity.get("image_quota"),
            "iat": now,
            "exp": now + self.settings.session_max_age_seconds,
        }
        encoded_payload = _b64encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        return f"{encoded_payload}.{self._signature(encoded_payload)}"

    def verify_token(self, token: str) -> dict[str, Any] | None:
        raw = str(token or "").strip()
        payload, sep, signature = raw.partition(".")
        if not sep or not payload or not signature:
            return None
        expected = self._signature(payload)
        if not hmac.compare_digest(signature, expected):
            return None
        try:
            data = json.loads(_b64decode(payload).decode("utf-8"))
        except Exception:
            return None
        if int(data.get("exp") or 0) < int(time.time()):
            return None
        if data.get("role") not in {"admin", "user"}:
            return None
        if not str(data.get("id") or "").strip():
            return None
        return data

    def set_cookie(self, response: Response, identity: dict[str, Any]) -> None:
        token = self.create_token(identity)
        response.set_cookie(
            self.settings.session_cookie_name,
            token,
            max_age=self.settings.session_max_age_seconds,
            httponly=True,
            secure=self.settings.secure_cookies,
            samesite="none" if self.settings.secure_cookies else "lax",
            path="/",
        )

    def clear_cookie(self, response: Response) -> None:
        response.delete_cookie(
            self.settings.session_cookie_name,
            path="/",
            secure=self.settings.secure_cookies,
            samesite="none" if self.settings.secure_cookies else "lax",
        )


web_session_service = WebSessionService(config.web_session_settings)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest test/test_web_session_service.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/web_session_service.py test/test_web_session_service.py
git commit -m "feat: add signed web sessions"
```

## Task 4: Add OIDC Provider Service

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `services/oidc_service.py`
- Test: `test/test_oidc_service.py`

- [ ] **Step 1: Add PyJWT crypto dependency**

Modify `pyproject.toml` dependencies:

```toml
    "pyjwt[crypto]>=2.10.0",
```

Run: `uv lock`

Expected: `uv.lock` updates with PyJWT and cryptography dependencies.

- [ ] **Step 2: Write failing OIDC service tests**

Create `test/test_oidc_service.py`:

```python
from services.oidc_config import OIDCSettings
from services.oidc_service import OIDCLoginError, OIDCProviderService


class FakeProvider(OIDCProviderService):
    def __init__(self):
        super().__init__(OIDCSettings.from_mapping({
            "oidc_enabled": True,
            "oidc_issuer": "https://idp.example.com",
            "oidc_client_id": "client-id",
            "oidc_client_secret": "client-secret",
            "oidc_allowed_email_domains": "example.com",
        }))

    def discovery(self):
        return {
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
            "userinfo_endpoint": "https://idp.example.com/userinfo",
            "jwks_uri": "https://idp.example.com/jwks",
            "issuer": "https://idp.example.com",
        }


def test_start_login_builds_authorize_url():
    service = FakeProvider()

    started = service.start_login("http://127.0.0.1:8000/api/auth/oidc/callback", "/image")

    assert started.session_id
    assert "https://idp.example.com/authorize?" in started.authorize_url
    assert "client_id=client-id" in started.authorize_url
    assert "code_challenge_method=S256" in started.authorize_url


def test_email_domain_allowlist_rejects_other_domain():
    service = FakeProvider()

    try:
        service.enforce_allowed_email("alice@other.test")
    except OIDCLoginError as exc:
        assert "不在允许范围" in str(exc)
    else:
        raise AssertionError("expected OIDCLoginError")


def test_email_domain_allowlist_accepts_configured_domain():
    service = FakeProvider()

    service.enforce_allowed_email("alice@example.com")
```

- [ ] **Step 3: Run tests and verify they fail**

Run: `uv run pytest test/test_oidc_service.py -q`

Expected: fails because `services.oidc_service` does not exist.

- [ ] **Step 4: Implement OIDC service skeleton with secure transaction handling**

Create `services/oidc_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import secrets
import threading
import time
from typing import Any
from urllib.parse import urlencode

import jwt
from curl_cffi import requests

from services.config import config
from services.oidc_config import OIDCSettings
from utils.pkce import generate_pkce


class OIDCLoginError(Exception):
    pass


@dataclass(frozen=True)
class OIDCStartResult:
    session_id: str
    authorize_url: str
    expires_in: int


@dataclass(frozen=True)
class OIDCClaims:
    subject: str
    email: str
    email_verified: bool
    name: str


class OIDCProviderService:
    _SESSION_TTL_SECONDS = 10 * 60

    def __init__(self, settings: OIDCSettings):
        self.settings = settings
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._discovery_cache: dict[str, Any] | None = None

    def is_enabled(self) -> bool:
        return bool(
            self.settings.enabled
            and self.settings.issuer
            and self.settings.client_id
            and self.settings.client_secret
        )

    def discovery(self) -> dict[str, Any]:
        if self._discovery_cache is not None:
            return self._discovery_cache
        issuer = self.settings.issuer.rstrip("/")
        response = requests.get(f"{issuer}/.well-known/openid-configuration", timeout=20)
        data = response.json()
        if response.status_code != 200 or not isinstance(data, dict):
            raise OIDCLoginError("OIDC discovery 失败")
        self._discovery_cache = data
        return data

    def _purge_expired_locked(self) -> None:
        now = time.time()
        expired = [sid for sid, item in self._sessions.items() if now - item["created_at"] > self._SESSION_TTL_SECONDS]
        for sid in expired:
            self._sessions.pop(sid, None)

    def start_login(self, redirect_uri: str, next_path: str = "") -> OIDCStartResult:
        if not self.is_enabled():
            raise OIDCLoginError("OIDC 登录尚未启用")
        metadata = self.discovery()
        verifier, challenge = generate_pkce()
        session_id = secrets.token_urlsafe(24)
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        with self._lock:
            self._purge_expired_locked()
            self._sessions[session_id] = {
                "state": state,
                "nonce": nonce,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
                "next_path": next_path,
                "created_at": time.time(),
            }
        params = {
            "client_id": self.settings.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self.settings.scopes,
            "state": f"{session_id}.{state}",
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return OIDCStartResult(
            session_id=session_id,
            authorize_url=f"{metadata['authorization_endpoint']}?{urlencode(params)}",
            expires_in=self._SESSION_TTL_SECONDS,
        )

    def _take_session(self, state: str) -> dict[str, Any]:
        session_id, sep, state_value = str(state or "").partition(".")
        if not sep or not session_id or not state_value:
            raise OIDCLoginError("OIDC state 无效，请重新登录")
        with self._lock:
            self._purge_expired_locked()
            session = self._sessions.pop(session_id, None)
        if not session or session.get("state") != state_value:
            raise OIDCLoginError("OIDC state 不匹配，请重新登录")
        return session

    def exchange_code(self, code: str, session: dict[str, Any]) -> dict[str, Any]:
        metadata = self.discovery()
        response = requests.post(
            metadata["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
                "code": code,
                "redirect_uri": session["redirect_uri"],
                "code_verifier": session["code_verifier"],
            },
            timeout=30,
        )
        data = response.json()
        if response.status_code != 200 or not isinstance(data, dict) or not data.get("id_token"):
            raise OIDCLoginError("OIDC token 交换失败")
        return data

    def validate_id_token(self, id_token: str, nonce: str) -> dict[str, Any]:
        metadata = self.discovery()
        signing_key = jwt.PyJWKClient(metadata["jwks_uri"]).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=self.settings.client_id,
            issuer=self.settings.issuer.rstrip("/"),
        )
        if str(claims.get("nonce") or "") != nonce:
            raise OIDCLoginError("OIDC nonce 不匹配，请重新登录")
        return claims

    def enforce_allowed_email(self, email: str) -> None:
        normalized = str(email or "").strip().lower()
        if not self.settings.allowed_email_domains:
            return
        domain = normalized.rsplit("@", 1)[-1] if "@" in normalized else ""
        if domain not in self.settings.allowed_email_domains:
            raise OIDCLoginError("当前邮箱不在允许登录范围内")

    def claims_from_token_claims(self, claims: dict[str, Any]) -> OIDCClaims:
        subject = str(claims.get("sub") or "").strip()
        if not subject:
            raise OIDCLoginError("OIDC 用户缺少 sub")
        email = str(claims.get("email") or "").strip().lower()
        self.enforce_allowed_email(email)
        return OIDCClaims(
            subject=subject,
            email=email,
            email_verified=bool(claims.get("email_verified", False)),
            name=str(claims.get("name") or claims.get("preferred_username") or email or "OIDC 用户").strip(),
        )

    def finish_login(self, code: str, state: str) -> tuple[OIDCClaims, str]:
        session = self._take_session(state)
        tokens = self.exchange_code(code, session)
        claims = self.validate_id_token(str(tokens["id_token"]), str(session["nonce"]))
        return self.claims_from_token_claims(claims), str(session.get("next_path") or "")


oidc_provider_service = OIDCProviderService(config.oidc_settings)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest test/test_oidc_service.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock services/oidc_service.py test/test_oidc_service.py
git commit -m "feat: add oidc provider service"
```

## Task 5: Add Cookie-Aware Auth API Routes

**Files:**
- Create: `api/auth.py`
- Modify: `api/app.py`
- Modify: `api/support.py`
- Test: `test/test_web_auth_api.py`

- [ ] **Step 1: Write failing API tests**

Create `test/test_web_auth_api.py`:

```python
from fastapi.testclient import TestClient

from api.app import create_app


def test_session_without_cookie_returns_401():
    client = TestClient(create_app())

    response = client.get("/api/auth/session")

    assert response.status_code == 401


def test_v1_models_does_not_accept_cookie_only(monkeypatch):
    client = TestClient(create_app())
    client.cookies.set("happyimage_session", "not-a-real-session")

    response = client.get("/v1/models")

    assert response.status_code == 401
```

- [ ] **Step 2: Run tests and verify session route fails**

Run: `uv run pytest test/test_web_auth_api.py -q`

Expected: first test returns `404` for `/api/auth/session`; second test returns `401`.

- [ ] **Step 3: Add support helpers**

Modify `api/support.py` imports:

```python
from services.web_session_service import web_session_service
```

Add helpers:

```python
def require_web_or_bearer_identity(request: Request, authorization: str | None) -> dict[str, object]:
    bearer = extract_bearer_token(authorization)
    if bearer:
        identity = _legacy_admin_identity(bearer) or auth_service.authenticate(bearer)
        if identity is not None:
            return identity
    cookie_name = web_session_service.settings.session_cookie_name
    session_token = request.cookies.get(cookie_name, "")
    session_identity = web_session_service.verify_token(session_token)
    if session_identity is None:
        raise HTTPException(status_code=401, detail={"error": "登录已失效，请重新登录"})
    current = auth_service.get_key(str(session_identity.get("id") or ""))
    if current is None or not bool(current.get("enabled", True)):
        raise HTTPException(status_code=401, detail={"error": "用户不存在或已被禁用"})
    return current
```

Keep `require_identity()` unchanged for Bearer-only `/v1/*`.

- [ ] **Step 4: Add auth router**

Create `api/auth.py`:

```python
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel

from api.support import require_web_or_bearer_identity
from services.auth_service import auth_service
from services.config import config
from services.oidc_service import OIDCLoginError, oidc_provider_service
from services.web_session_service import web_session_service


class OIDCStartRequest(BaseModel):
    next: str = ""


def _safe_next(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate.startswith("/") or candidate.startswith("//") or "\\" in candidate:
        return "/image"
    if candidate == "/login" or candidate.startswith("/login?"):
        return "/image"
    return candidate


def _identity_response(identity: dict[str, object]) -> dict[str, object]:
    role = "admin" if identity.get("role") == "admin" else "user"
    return {
        "ok": True,
        "role": role,
        "subject_id": str(identity.get("id") or role),
        "name": str(identity.get("name") or ("管理员" if role == "admin" else "创作者")),
        "image_quota": identity.get("image_quota") if role == "user" else None,
        "user": {
            "id": str(identity.get("id") or role),
            "name": str(identity.get("name") or ("管理员" if role == "admin" else "创作者")),
            "role": role,
            "image_quota": identity.get("image_quota") if role == "user" else None,
        },
    }


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/auth/config")
    async def auth_config():
        return {"oidc": config.get_oidc_settings_public()}

    @router.get("/api/auth/session")
    async def get_session(request: Request, authorization: str | None = Header(default=None)):
        identity = require_web_or_bearer_identity(request, authorization)
        return _identity_response(identity)

    @router.post("/api/auth/logout")
    async def logout():
        response = Response(content='{"ok":true}', media_type="application/json")
        web_session_service.clear_cookie(response)
        return response

    @router.post("/api/auth/oidc/start")
    async def oidc_start(body: OIDCStartRequest):
        session_settings = config.web_session_settings
        redirect_uri = f"{session_settings.api_base_url}/api/auth/oidc/callback"
        try:
            started = await run_in_threadpool(oidc_provider_service.start_login, redirect_uri, _safe_next(body.next))
        except OIDCLoginError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {
            "authorize_url": started.authorize_url,
            "expires_in": started.expires_in,
        }

    @router.get("/api/auth/oidc/callback")
    async def oidc_callback(code: str = "", state: str = ""):
        try:
            claims, next_path = await run_in_threadpool(oidc_provider_service.finish_login, code, state)
            existing = auth_service.find_by_auth_binding("oidc", claims.subject)
            if existing is None:
                conflict = auth_service.find_email_conflict(claims.email, provider="oidc", subject=claims.subject)
                if conflict is not None:
                    raise OIDCLoginError("已有同邮箱本地用户，请联系管理员绑定后再登录")
                existing = auth_service.create_oidc_user(
                    provider="oidc",
                    subject=claims.subject,
                    email=claims.email,
                    name=claims.name,
                    image_quota=config.oidc_settings.default_image_quota,
                )
            if not bool(existing.get("enabled", True)):
                raise OIDCLoginError("账号已被禁用")
        except OIDCLoginError as exc:
            target = f"{config.web_session_settings.frontend_base_url}/login?error={quote(str(exc))}"
            return RedirectResponse(target, status_code=302)
        target = f"{config.web_session_settings.frontend_base_url}{_safe_next(next_path)}"
        response = RedirectResponse(target, status_code=302)
        web_session_service.set_cookie(response, existing)
        return response

    return router
```

- [ ] **Step 5: Wire router and credentialed CORS**

Modify `api/app.py` imports:

```python
from api import accounts, ai, auth, image_tasks, seed_gallery, share_drafts, system
```

Replace the CORS middleware configuration:

```python
    web_session_settings = config.web_session_settings
    cors_origins = web_session_settings.cors_origins or ["http://127.0.0.1:3000"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

Include the new router:

```python
    app.include_router(auth.create_router())
```

Place it before `system.create_router(app_version)`.

- [ ] **Step 6: Run tests**

Run: `uv run pytest test/test_web_auth_api.py test/test_v1_models.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add api/auth.py api/app.py api/support.py test/test_web_auth_api.py
git commit -m "feat: add cookie web auth routes"
```

## Task 6: Frontend Session and Login Flow

**Files:**
- Modify: `web/src/constants/common-env.ts`
- Modify: `web/src/lib/request.ts`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/store/auth.ts`
- Modify: `web/src/lib/auth-session.ts`
- Modify: `web/src/app/login/page.tsx`

- [ ] **Step 1: Update frontend API base URL config**

Modify `web/src/constants/common-env.ts`:

```ts
const webConfig = {
  apiUrl: (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, ""),
  appVersion: process.env.NEXT_PUBLIC_APP_VERSION || "0.0.0",
};

export default webConfig;
```

- [ ] **Step 2: Enable credentialed API requests**

Modify `web/src/lib/request.ts` axios creation:

```ts
export const request = axios.create({
  baseURL: webConfig.apiUrl,
  withCredentials: true,
});
```

Keep the existing Authorization interceptor, but only set Bearer when a stored key exists:

```ts
    if (authKey && !headers.Authorization) {
        headers.Authorization = `Bearer ${authKey}`;
    }
```

- [ ] **Step 3: Add auth API functions**

Modify `web/src/lib/api.ts`:

```ts
export type AuthConfigResponse = {
  oidc: {
    enabled: boolean;
    issuer: string;
    client_id: string;
    has_client_secret: boolean;
    scopes: string;
    allowed_email_domains: string[];
    default_image_quota: number;
  };
};

export async function fetchAuthConfig() {
  return httpRequest<AuthConfigResponse>("/api/auth/config", {
    redirectOnUnauthorized: false,
  });
}

export async function fetchCurrentSession() {
  return httpRequest<LoginResponse>("/api/auth/session", {
    redirectOnUnauthorized: false,
  });
}

export async function startOIDCLogin(nextPath: string) {
  return httpRequest<{ authorize_url: string; expires_in: number }>("/api/auth/oidc/start", {
    method: "POST",
    body: { next: nextPath },
    redirectOnUnauthorized: false,
  });
}

export async function logout() {
  return httpRequest<{ ok: boolean }>("/api/auth/logout", {
    method: "POST",
    redirectOnUnauthorized: false,
  });
}
```

- [ ] **Step 4: Allow cookie sessions in local auth store**

Modify `StoredAuthSession` in `web/src/store/auth.ts`:

```ts
export type StoredAuthSession = {
  key?: string;
  role: AuthRole;
  subjectId: string;
  name: string;
  imageQuota?: number | null;
  authMode?: "cookie" | "bearer";
};
```

Modify `normalizeSession()` so `key` is optional when `authMode === "cookie"`:

```ts
  const key = String(candidate.key || fallbackKey || "").trim();
  const role = candidate.role === "admin" || candidate.role === "user" ? candidate.role : null;
  const authMode = candidate.authMode === "cookie" ? "cookie" : "bearer";
  if (!role || (authMode === "bearer" && !key)) {
    return null;
  }
```

Return `authMode`:

```ts
    key,
    role,
    subjectId: String(candidate.subjectId || "").trim(),
    name: String(candidate.name || "").trim(),
    imageQuota: typeof candidate.imageQuota === "number" ? candidate.imageQuota : null,
    authMode,
```

- [ ] **Step 5: Validate sessions through backend session endpoint**

Modify `web/src/lib/auth-session.ts`:

```ts
"use client";

import { fetchCurrentSession } from "@/lib/api";
import { clearStoredAuthSession, getStoredAuthSession, setStoredAuthSession, type StoredAuthSession } from "@/store/auth";

export async function getValidatedAuthSession(): Promise<StoredAuthSession | null> {
  try {
    const data = await fetchCurrentSession();
    const nextSession: StoredAuthSession = {
      key: data.access_token || (await getStoredAuthSession())?.key || "",
      role: data.role,
      subjectId: data.subject_id,
      name: data.name,
      imageQuota: data.user?.image_quota ?? data.image_quota ?? null,
      authMode: data.access_token ? "bearer" : "cookie",
    };
    await setStoredAuthSession(nextSession);
    return nextSession;
  } catch {
    await clearStoredAuthSession();
    return null;
  }
}
```

- [ ] **Step 6: Add OIDC login button**

Modify `web/src/app/login/page.tsx` imports:

```ts
import { fetchAuthConfig, loginWithAccessKey, loginWithPassword, startOIDCLogin, type LoginResponse } from "@/lib/api";
```

Add state:

```ts
  const [oidcEnabled, setOidcEnabled] = useState(false);
  const [isStartingOIDC, setIsStartingOIDC] = useState(false);
```

Load config:

```ts
  useEffect(() => {
    let active = true;
    fetchAuthConfig()
      .then((data) => {
        if (active) {
          setOidcEnabled(Boolean(data.oidc?.enabled));
        }
      })
      .catch(() => {
        if (active) {
          setOidcEnabled(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);
```

Add handler:

```ts
  const handleOIDCLogin = async () => {
    setIsStartingOIDC(true);
    try {
      const data = await startOIDCLogin(getNextPathFromLocation() || getDefaultRouteForRole("user"));
      window.location.assign(data.authorize_url);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "OAuth 登录启动失败");
      setIsStartingOIDC(false);
    }
  };
```

Render a button above local login form:

```tsx
          {oidcEnabled ? (
            <Button
              type="button"
              className="h-11 w-full rounded-xl bg-stone-950 text-white hover:bg-stone-800"
              onClick={() => void handleOIDCLogin()}
              disabled={isSubmitting || isStartingOIDC}
            >
              {isStartingOIDC ? <LoaderCircle className="size-4 animate-spin" /> : <KeyRound className="size-4" />}
              使用 OAuth 登录
            </Button>
          ) : null}
```

- [ ] **Step 7: Run frontend checks**

Run:

```bash
cd web
pnpm lint
pnpm build
```

Expected: both commands pass.

- [ ] **Step 8: Commit**

```bash
git add web/src/constants/common-env.ts web/src/lib/request.ts web/src/lib/api.ts web/src/store/auth.ts web/src/lib/auth-session.ts web/src/app/login/page.tsx
git commit -m "feat: add frontend oidc session flow"
```

## Task 7: Add Admin OIDC Settings UI

**Files:**
- Create: `web/src/app/settings/components/oidc-settings-card.tsx`
- Modify: `web/src/app/settings/page.tsx`
- Modify: `web/src/lib/api.ts`
- Test: existing frontend build

- [ ] **Step 1: Add OIDC settings API types**

Modify `web/src/lib/api.ts`:

```ts
export type OIDCSettingsUpdate = {
  oidc_enabled?: boolean;
  oidc_issuer?: string;
  oidc_client_id?: string;
  oidc_client_secret?: string;
  oidc_scopes?: string;
  oidc_allowed_email_domains?: string;
  oidc_default_image_quota?: number;
};

export async function saveOIDCSettings(settings: OIDCSettingsUpdate) {
  return httpRequest<SettingsResponse>("/api/settings", {
    method: "POST",
    body: settings,
  });
}
```

- [ ] **Step 2: Create settings card**

Create `web/src/app/settings/components/oidc-settings-card.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { LoaderCircle, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { fetchSettings, saveOIDCSettings } from "@/lib/api";

export function OIDCSettingsCard() {
  const [enabled, setEnabled] = useState(false);
  const [issuer, setIssuer] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [hasClientSecret, setHasClientSecret] = useState(false);
  const [scopes, setScopes] = useState("openid profile email");
  const [domains, setDomains] = useState("");
  const [quota, setQuota] = useState("0");
  const [isSaving, setIsSaving] = useState(false);

  const load = async () => {
    const data = await fetchSettings();
    const oidc = data.config.oidc;
    setEnabled(Boolean(oidc?.enabled));
    setIssuer(String(oidc?.issuer || ""));
    setClientId(String(oidc?.client_id || ""));
    setHasClientSecret(Boolean(oidc?.has_client_secret));
    setScopes(String(oidc?.scopes || "openid profile email"));
    setDomains(Array.isArray(oidc?.allowed_email_domains) ? oidc.allowed_email_domains.join(", ") : "");
    setQuota(String(Math.max(0, Number(oidc?.default_image_quota || 0))));
  };

  useEffect(() => {
    void load();
  }, []);

  const save = async () => {
    setIsSaving(true);
    try {
      await saveOIDCSettings({
        oidc_enabled: enabled,
        oidc_issuer: issuer.trim(),
        oidc_client_id: clientId.trim(),
        oidc_client_secret: clientSecret.trim(),
        oidc_scopes: scopes.trim() || "openid profile email",
        oidc_allowed_email_domains: domains.trim(),
        oidc_default_image_quota: Math.max(0, Math.floor(Number(quota) || 0)),
      });
      setClientSecret("");
      toast.success("OIDC 设置已保存");
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存 OIDC 设置失败");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
      <CardContent className="space-y-5 p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold tracking-[0.18em] text-stone-500 uppercase">
              <ShieldCheck className="size-3.5" />
              OAuth / OIDC
            </div>
            <h2 className="mt-2 text-lg font-semibold tracking-tight">第三方登录</h2>
            <p className="mt-1 text-sm text-stone-500">配置通用 OIDC Provider，首次登录会自动创建普通用户，默认额度为 0。</p>
          </div>
          <Badge variant={enabled ? "success" : "secondary"}>{enabled ? "已启用" : "未启用"}</Badge>
        </div>

        <label className="flex items-center gap-2 text-sm text-stone-700">
          <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
          启用 OIDC 登录
        </label>

        <div className="grid gap-3 md:grid-cols-2">
          <Input value={issuer} onChange={(event) => setIssuer(event.target.value)} placeholder="https://idp.example.com" />
          <Input value={clientId} onChange={(event) => setClientId(event.target.value)} placeholder="Client ID" />
          <Input value={clientSecret} onChange={(event) => setClientSecret(event.target.value)} placeholder={hasClientSecret ? "已配置，留空表示不修改" : "Client Secret"} type="password" />
          <Input value={scopes} onChange={(event) => setScopes(event.target.value)} placeholder="openid profile email" />
          <Input value={domains} onChange={(event) => setDomains(event.target.value)} placeholder="example.com, team.example.com" />
          <Input value={quota} onChange={(event) => setQuota(event.target.value)} placeholder="0" inputMode="numeric" />
        </div>

        <Button className="rounded-xl" onClick={() => void save()} disabled={isSaving}>
          {isSaving ? <LoaderCircle className="size-4 animate-spin" /> : null}
          保存 OIDC 设置
        </Button>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 3: Render settings card**

Modify `web/src/app/settings/page.tsx` imports:

```ts
import { OIDCSettingsCard } from "./components/oidc-settings-card";
```

Render `<OIDCSettingsCard />` in the settings grid near other security/config cards.

- [ ] **Step 4: Run frontend checks**

Run:

```bash
cd web
pnpm lint
pnpm build
```

Expected: both commands pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/app/settings/components/oidc-settings-card.tsx web/src/app/settings/page.tsx web/src/lib/api.ts
git commit -m "feat: add oidc settings card"
```

## Task 8: Split Docker Backend and Frontend Services

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.local.yml`
- Modify: `.dockerignore` if frontend/server artifacts need exclusion

- [ ] **Step 1: Add separate Docker targets**

Modify `Dockerfile` so the Python runtime target is named `api` and a new frontend runtime target is named `web`:

```dockerfile
FROM ${PYTHON_IMAGE} AS api
```

Keep backend copy commands, but remove:

```dockerfile
COPY --from=web-build /app/web/out ./web_dist
```

Add a final web target:

```dockerfile
FROM nginx:1.27-alpine AS web

COPY --from=web-build /app/web/out /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

- [ ] **Step 2: Remove backend static fallback**

Modify `api/app.py` `serve_web()` behavior so the backend no longer serves frontend pages. Replace the fallback route body with:

```python
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_web(full_path: str):
        clean_path = full_path.strip("/")
        if clean_path.startswith(("images/", "image-thumbnails/")):
            asset = resolve_web_asset(full_path)
            if asset is not None:
                return FileResponse(asset, headers=web_asset_cache_headers(full_path))
        raise HTTPException(status_code=404, detail="Not Found")
```

If `resolve_web_asset` is no longer used by image routes after this change, remove unused imports in the same task.

- [ ] **Step 3: Split production compose services**

Modify `docker-compose.yml` to define:

```yaml
services:
  happyimage-api:
    build:
      context: .
      dockerfile: Dockerfile
      target: api
      args:
        PYTHON_IMAGE: ${HAPPYIMAGE_PYTHON_IMAGE:-python:3.13-slim}
    image: happyimage-api:latest
    container_name: happyimage-api
    restart: unless-stopped
    ports:
      - "8000:80"
    volumes:
      - ./data:/app/data
      - ./config.json:/app/config.json:rw
    environment:
      STORAGE_BACKEND: ${STORAGE_BACKEND:-json}
      DATABASE_URL: ${DATABASE_URL:-}
      HAPPYIMAGE_AUTH_KEY: ${HAPPYIMAGE_AUTH_KEY:-}
      HAPPYIMAGE_FRONTEND_BASE_URL: ${HAPPYIMAGE_FRONTEND_BASE_URL:-http://localhost:3000}
      HAPPYIMAGE_API_BASE_URL: ${HAPPYIMAGE_API_BASE_URL:-http://localhost:8000}
      HAPPYIMAGE_CORS_ORIGINS: ${HAPPYIMAGE_CORS_ORIGINS:-http://localhost:3000}
      HAPPYIMAGE_SESSION_SECRET: ${HAPPYIMAGE_SESSION_SECRET:-}
      HAPPYIMAGE_SECURE_COOKIES: ${HAPPYIMAGE_SECURE_COOKIES:-false}
      HAPPYIMAGE_OIDC_ENABLED: ${HAPPYIMAGE_OIDC_ENABLED:-false}
      HAPPYIMAGE_OIDC_ISSUER: ${HAPPYIMAGE_OIDC_ISSUER:-}
      HAPPYIMAGE_OIDC_CLIENT_ID: ${HAPPYIMAGE_OIDC_CLIENT_ID:-}
      HAPPYIMAGE_OIDC_CLIENT_SECRET: ${HAPPYIMAGE_OIDC_CLIENT_SECRET:-}
      HAPPYIMAGE_OIDC_ALLOWED_EMAIL_DOMAINS: ${HAPPYIMAGE_OIDC_ALLOWED_EMAIL_DOMAINS:-}
      HAPPYIMAGE_OIDC_DEFAULT_IMAGE_QUOTA: ${HAPPYIMAGE_OIDC_DEFAULT_IMAGE_QUOTA:-0}
      HAPPYIMAGE_PROXY: ${HAPPYIMAGE_PROXY:-}
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1/health?format=json', timeout=3).read()"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s

  happyimage-web:
    build:
      context: .
      dockerfile: Dockerfile
      target: web
      args:
        NODE_IMAGE: ${HAPPYIMAGE_NODE_IMAGE:-node:22-alpine}
    image: happyimage-web:latest
    container_name: happyimage-web
    restart: unless-stopped
    ports:
      - "3000:80"
    depends_on:
      happyimage-api:
        condition: service_healthy
```

- [ ] **Step 4: Split local compose services**

Modify `docker-compose.local.yml` with the same two-service shape, using SQLite defaults:

```yaml
      STORAGE_BACKEND: ${STORAGE_BACKEND:-sqlite}
      DATABASE_URL: ${DATABASE_URL:-sqlite:////app/data/accounts.db}
```

Use local URLs:

```yaml
      HAPPYIMAGE_FRONTEND_BASE_URL: ${HAPPYIMAGE_FRONTEND_BASE_URL:-http://127.0.0.1:3000}
      HAPPYIMAGE_API_BASE_URL: ${HAPPYIMAGE_API_BASE_URL:-http://127.0.0.1:8000}
      HAPPYIMAGE_CORS_ORIGINS: ${HAPPYIMAGE_CORS_ORIGINS:-http://127.0.0.1:3000}
      HAPPYIMAGE_SECURE_COOKIES: ${HAPPYIMAGE_SECURE_COOKIES:-false}
```

- [ ] **Step 5: Build both images**

Run:

```bash
docker compose -f docker-compose.local.yml build happyimage-api happyimage-web
```

Expected: both targets build successfully.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-compose.yml docker-compose.local.yml api/app.py
git commit -m "feat: split web and api docker services"
```

## Task 9: Documentation and Regression Pass

**Files:**
- Modify: `README.md`
- Modify: `docs/docker-deployment.md`
- Modify: `docs/feature-status.en.md`

- [ ] **Step 1: Update README quick start**

Modify the Docker run section to show:

```bash
cp .env.example .env
cp config.example.json config.json
# edit HAPPYIMAGE_AUTH_KEY and HAPPYIMAGE_SESSION_SECRET
docker compose up -d --build happyimage-api happyimage-web
curl -sf http://localhost:8000/health?format=json
open http://localhost:3000
```

Add this wording:

```markdown
HappyImage now runs as two services by default: `happyimage-api` for FastAPI and OpenAI-compatible APIs, and `happyimage-web` for the frontend. Set `HAPPYIMAGE_FRONTEND_BASE_URL`, `HAPPYIMAGE_API_BASE_URL`, and `HAPPYIMAGE_CORS_ORIGINS` when deploying behind custom domains.
```

- [ ] **Step 2: Document OIDC configuration**

Add to `docs/docker-deployment.md`:

````markdown
### HappyImage OIDC Login

OIDC login is for HappyImage web users. It is separate from OpenAI account OAuth import in the account pool.

Set:

```bash
HAPPYIMAGE_OIDC_ENABLED=true
HAPPYIMAGE_OIDC_ISSUER=https://idp.example.com
HAPPYIMAGE_OIDC_CLIENT_ID=happyimage
HAPPYIMAGE_OIDC_CLIENT_SECRET=replace_with_secret
HAPPYIMAGE_OIDC_ALLOWED_EMAIL_DOMAINS=example.com
HAPPYIMAGE_OIDC_DEFAULT_IMAGE_QUOTA=0
```

Configure the provider redirect URI as:

```text
https://api.example.com/api/auth/oidc/callback
```

For cross-site production deployments, use HTTPS and keep `HAPPYIMAGE_SECURE_COOKIES=true`.
````

- [ ] **Step 3: Update feature status**

Add a feature-status entry:

```markdown
- HappyImage web login can use a generic OIDC provider. Browser UI sessions use HttpOnly cookies, while `/v1/*` remains Bearer-token based for external clients.
```

- [ ] **Step 4: Run backend regression tests**

Run:

```bash
uv run pytest test -q
```

Expected: test suite passes. If unrelated dirty worktree changes cause failures, record the failing tests and inspect whether they are caused by this feature before changing code.

- [ ] **Step 5: Run frontend regression checks**

Run:

```bash
cd web
pnpm lint
pnpm build
```

Expected: both commands pass.

- [ ] **Step 6: Verify working tree and commit docs**

Run:

```bash
git status --short
```

Expected: only documentation files from this task are unstaged.

Commit:

```bash
git add README.md docs/docker-deployment.md docs/feature-status.en.md
git commit -m "docs: document oidc split deployment"
```

## Final Verification Checklist

- [ ] `uv run pytest test/test_oidc_config.py test/test_oidc_auth_service.py test/test_web_session_service.py test/test_oidc_service.py test/test_web_auth_api.py -q` passes.
- [ ] `uv run pytest test/test_v1_models.py test/test_v1_images_generations.py test/test_image_tasks_api.py -q` passes.
- [ ] `cd web && pnpm lint && pnpm build` passes.
- [ ] `docker compose -f docker-compose.local.yml build happyimage-api happyimage-web` passes.
- [ ] `/api/auth/session` returns `401` without auth.
- [ ] `/v1/models` returns `401` with only a web cookie and no Bearer token.
- [ ] Admin access-key login still reaches `/accounts`.
- [ ] OIDC-created user appears in user management with `role=user` and `image_quota=0`.
- [ ] OIDC secrets are redacted in `/api/settings` responses.

## Self-Review Notes

- Spec coverage: tasks cover OIDC config, session cookies, provider flow, auto-created users, Bearer `/v1/*` compatibility, settings UI, split Docker deployment, and documentation.
- Intentional exclusions: multi-provider support, OIDC group-to-role mapping, provider logout, and OpenAI upstream account OAuth refactoring remain outside this plan.
- Type consistency: backend identity fields use existing `id`, `role`, `name`, and `image_quota`; OIDC binding metadata uses `auth_provider`, `auth_subject`, `email`, and `external_name`.
