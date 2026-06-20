"""Signed web session service for HappyImage browser sessions.

Creates and validates stateless signed session tokens stored in HttpOnly
cookies. Sessions contain the user identity needed by auth checks without
exposing provider access tokens to the browser.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from base64 import urlsafe_b64encode, urlsafe_b64decode
from typing import Any

from services.config import config


class WebSessionError(Exception):
    """Raised when a session is invalid, expired, or tampered with."""


def _b64_encode(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64_decode(data: str) -> bytes:
    padded = data + "=" * (4 - len(data) % 4) if len(data) % 4 else data
    return urlsafe_b64decode(padded.encode("ascii"))


class WebSessionService:
    """Stateless signed sessions stored as cookies."""

    def __init__(self) -> None:
        pass

    @property
    def _secret(self) -> str:
        secret = config.session_secret
        if not secret:
            raise WebSessionError("HAPPYIMAGE_SESSION_SECRET 未配置")
        return secret

    @property
    def cookie_name(self) -> str:
        return config.session_cookie_name

    @property
    def max_age(self) -> int:
        return config.session_max_age_seconds

    # ------------------------------------------------------------------
    # Session creation
    # ------------------------------------------------------------------

    def create_session_payload(self, identity: dict[str, object]) -> dict[str, Any]:
        """Build the data that goes into a signed session token."""
        now = int(time.time())
        payload = {
            "sub": str(identity.get("id") or ""),
            "name": str(identity.get("name") or ""),
            "role": str(identity.get("role") or "user"),
            "image_quota": identity.get("image_quota"),
            "iat": now,
            "exp": now + self.max_age,
        }
        for key in ("auth_provider", "auth_subject", "email"):
            value = str(identity.get(key) or "").strip()
            if value:
                payload[key] = value
        return payload

    def sign_session(self, payload: dict[str, Any]) -> str:
        """Sign a session payload into a token string."""
        secret = self._secret.encode("utf-8")
        header = _b64_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8"))
        body = _b64_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{header}.{body}"
        signature = hmac.new(secret, signing_input.encode("ascii"), hashlib.sha256).digest()
        return f"{signing_input}.{_b64_encode(signature)}"

    def verify_session(self, token: str) -> dict[str, Any]:
        """Verify a signed session token and return the payload.

        Raises WebSessionError on any validation failure.
        """
        if not token:
            raise WebSessionError("会话令牌为空")

        parts = token.split(".")
        if len(parts) != 3:
            raise WebSessionError("会话令牌格式无效")

        header_b64, body_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{body_b64}"

        # Verify signature
        secret = self._secret.encode("utf-8")
        expected_sig = hmac.new(secret, signing_input.encode("ascii"), hashlib.sha256).digest()
        try:
            actual_sig = _b64_decode(sig_b64)
        except Exception:
            raise WebSessionError("会话签名解码失败")

        if not hmac.compare_digest(expected_sig, actual_sig):
            raise WebSessionError("会话签名无效")

        # Decode payload
        try:
            payload_bytes = _b64_decode(body_b64)
            payload = json.loads(payload_bytes.decode("utf-8"))
        except Exception as exc:
            raise WebSessionError(f"会话数据解码失败: {exc}") from exc

        if not isinstance(payload, dict):
            raise WebSessionError("会话数据格式异常")

        # Check expiry
        exp = payload.get("exp")
        if isinstance(exp, (int, float)):
            if time.time() > exp:
                raise WebSessionError("会话已过期")

        # Validate required fields
        if not str(payload.get("sub") or "").strip():
            raise WebSessionError("会话缺少用户标识")

        return payload

    def session_to_identity(self, session_payload: dict[str, Any]) -> dict[str, object]:
        """Convert a verified session payload into an auth identity dict."""
        role = str(session_payload.get("role") or "user")
        if role not in {"admin", "user"}:
            role = "user"
        identity: dict[str, object] = {
            "id": str(session_payload.get("sub") or ""),
            "name": str(session_payload.get("name") or ""),
            "role": role,
        }
        if role == "user":
            quota = session_payload.get("image_quota")
            if quota is not None:
                identity["image_quota"] = quota
            for key in ("auth_provider", "auth_subject", "email"):
                value = str(session_payload.get(key) or "").strip()
                if value:
                    identity[key] = value
        return identity

    # ------------------------------------------------------------------
    # Cookie construction
    # ------------------------------------------------------------------

    def make_set_cookie_header(self, token: str) -> str:
        """Build a Set-Cookie header value for the session cookie."""
        parts = [
            f"{self.cookie_name}={token}",
            "HttpOnly",
            "Path=/",
        ]
        if config.api_base_url.startswith("https://"):
            parts.append("Secure")
        frontend = config.frontend_base_url
        if frontend and not frontend.startswith("http://127.") and not frontend.startswith("http://localhost"):
            parts.append("SameSite=None")
        else:
            parts.append("SameSite=Lax")
        parts.append(f"Max-Age={self.max_age}")
        return "; ".join(parts)

    def make_clear_cookie_header(self) -> str:
        """Build a Set-Cookie header value that clears the session cookie."""
        parts = [
            f"{self.cookie_name}=",
            "HttpOnly",
            "Path=/",
            "Max-Age=0",
        ]
        frontend = config.frontend_base_url
        if frontend and not frontend.startswith("http://127.") and not frontend.startswith("http://localhost"):
            parts.append("SameSite=None")
        else:
            parts.append("SameSite=Lax")
        return "; ".join(parts)

    # ------------------------------------------------------------------
    # High-level operations
    # ------------------------------------------------------------------

    def create_session(self, identity: dict[str, object]) -> tuple[str, str]:
        """Create a session for an identity.

        Returns (session_token, set_cookie_header_value).
        """
        payload = self.create_session_payload(identity)
        token = self.sign_session(payload)
        cookie = self.make_set_cookie_header(token)
        return token, cookie

    def resolve_identity(self, cookie_value: str) -> dict[str, object]:
        """Extract and validate a session cookie into an auth identity.

        Raises WebSessionError if the session is invalid.
        """
        payload = self.verify_session(cookie_value)
        return self.session_to_identity(payload)


web_session_service = WebSessionService()
