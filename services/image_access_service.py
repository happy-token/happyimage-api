from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

from fastapi import HTTPException

from services.config import config

IMAGE_ACCESS_TOKEN_PARAM = "image_token"
DEFAULT_IMAGE_ACCESS_TTL_SECONDS = 24 * 60 * 60


def _clean(value: object) -> str:
    return str(value or "").strip()


def _secret() -> str:
    return _clean(config.session_secret) or _clean(config.auth_key)


def _ttl_seconds() -> int:
    try:
        return max(60, int(config.data.get("image_access_token_ttl_seconds", DEFAULT_IMAGE_ACCESS_TTL_SECONDS)))
    except (AttributeError, TypeError, ValueError):
        return DEFAULT_IMAGE_ACCESS_TTL_SECONDS


def _signature(rel: str, expires_at: int) -> str:
    secret = _secret()
    if not secret:
        return ""
    payload = f"{rel}:{expires_at}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def create_image_access_token(rel: str, *, now: int | None = None) -> str:
    current = int(time.time() if now is None else now)
    expires_at = current + _ttl_seconds()
    signature = _signature(rel, expires_at)
    return f"{expires_at}.{signature}" if signature else ""


def append_image_access_token(url: str, rel: str) -> str:
    token = create_image_access_token(rel)
    if not token:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode({IMAGE_ACCESS_TOKEN_PARAM: token})}"


def verify_image_access_token(rel: str, token: str) -> None:
    secret = _secret()
    if not secret:
        raise HTTPException(status_code=403, detail="image access is not configured")

    raw_exp, sep, raw_sig = _clean(token).partition(".")
    if not sep or not raw_exp or not raw_sig:
        raise HTTPException(status_code=401, detail="image link is invalid or expired")
    try:
        expires_at = int(raw_exp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="image link is invalid or expired") from exc
    if expires_at < int(time.time()):
        raise HTTPException(status_code=401, detail="image link is invalid or expired")

    expected = _signature(rel, expires_at)
    if not hmac.compare_digest(expected, raw_sig):
        raise HTTPException(status_code=401, detail="image link is invalid or expired")
