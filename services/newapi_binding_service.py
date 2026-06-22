from __future__ import annotations

from collections.abc import Callable
from typing import Any

DEFAULT_NEWAPI_URL = "https://gateway.happy-token.cn"


def _clean(value: object) -> str:
    return str(value or "").strip()


class NewAPIBindingService:
    def __init__(
        self,
        *,
        settings: dict[str, object] | None = None,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    def ensure_default_token(
        self,
        provider: str,
        subject: str,
        email: str,
        name: str,
    ) -> dict[str, object]:
        settings = self._settings or self._load_settings()
        provision_url = _clean(settings.get("provision_url"))
        provision_secret = _clean(settings.get("provision_secret"))
        base_url = self._normalize_url(settings.get("base_url"), default=DEFAULT_NEWAPI_URL)
        management_url = self._normalize_url(settings.get("management_url"), default=base_url)
        if not bool(settings.get("enabled")) or not provision_url or not provision_secret:
            return {
                "ok": False,
                "status": "pending",
                "message": "NewAPI provisioning endpoint is not configured",
                "base_url": base_url,
                "management_url": management_url,
            }

        session = None
        try:
            session = self._make_session()
            response = session.post(
                provision_url,
                headers={
                    "Authorization": f"Bearer {provision_secret}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={
                    "provider": _clean(provider),
                    "subject": _clean(subject),
                    "email": _clean(email),
                    "name": _clean(name),
                    "token_name": _clean(settings.get("token_name")) or "HappyImage Default",
                },
                timeout=20,
            )
            status_code = int(getattr(response, "status_code", 0) or 0)
            if status_code != 200:
                return self._failed(status_code)
            data = self._response_json(response)
            if not isinstance(data, dict) or data.get("ok") is not True or not _clean(data.get("token")):
                return self._failed(message="NewAPI provisioning returned an invalid response")
            return {
                "ok": True,
                "status": "configured",
                "user_id": _clean(data.get("user_id")),
                "token_id": _clean(data.get("token_id")),
                "token": _clean(data.get("token")),
                "base_url": self._normalize_url(data.get("base_url") or base_url, default=DEFAULT_NEWAPI_URL),
                "management_url": self._normalize_url(
                    data.get("management_url")
                    or management_url
                    or data.get("base_url")
                    or base_url,
                    default=DEFAULT_NEWAPI_URL,
                ),
            }
        except Exception:
            return self._failed(message="NewAPI provisioning request failed")
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    def _make_session(self) -> Any:
        if self._session_factory is not None:
            return self._session_factory()

        from curl_cffi import requests
        from services.proxy_service import proxy_settings

        kwargs = proxy_settings.build_session_kwargs(impersonate="chrome", verify=True)
        return requests.Session(**kwargs)

    @staticmethod
    def _load_settings() -> dict[str, object]:
        from services.config import config

        return config.get_newapi_binding_settings()

    @staticmethod
    def _normalize_url(value: object, *, default: str = "") -> str:
        return (_clean(value) or default).rstrip("/")

    @staticmethod
    def _response_json(response: object) -> object:
        try:
            text = getattr(response, "text", "")
            if text == "":
                return {}
            return response.json()
        except Exception:
            return {}

    @staticmethod
    def _failed(http_status: int | None = None, *, message: str | None = None) -> dict[str, object]:
        result: dict[str, object] = {
            "ok": False,
            "status": "failed",
            "message": message or "NewAPI provisioning failed",
        }
        if http_status is not None:
            result["http_status"] = http_status
        return result


newapi_binding_service = NewAPIBindingService()
