from __future__ import annotations

from collections.abc import Callable
import secrets
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from utils.log import logger

DEFAULT_NEWAPI_URL = "https://gateway.happy-token.cn"


def _clean(value: object) -> str:
    return str(value or "").strip()


def _normalize_url(value: object, *, default: str = "") -> str:
    return (_clean(value) or default).rstrip("/")


def _normalize_management_url(value: object) -> str:
    return _normalize_url(value).removesuffix("/v1")


class NewAPIBindingService:
    def __init__(
        self,
        *,
        settings: dict[str, object] | None = None,
        session_factory: Callable[[], Any] | None = None,
        sql_connect_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._sql_connect_factory = sql_connect_factory

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
        base_url = _normalize_url(
            settings.get("gateway_api_base_url") or settings.get("base_url"),
            default=DEFAULT_NEWAPI_URL,
        )
        model_base_url = self._normalize_model_base_url(base_url)
        management_url = _normalize_management_url(
            settings.get("gateway_management_url") or settings.get("management_url")
        )
        if not management_url:
            management_url = _normalize_management_url(base_url)
        if (
            not bool(settings.get("enabled"))
            or (not provision_url and not _clean(settings.get("sql_dsn")))
        ):
            return {
                "ok": False,
                "status": "pending",
                "message": "NewAPI provisioning endpoint is not configured",
                "base_url": model_base_url,
                "management_url": management_url,
            }
        if not provision_url:
            return self._ensure_default_token_via_sql(
                settings=settings,
                provider=provider,
                subject=subject,
                email=email,
                name=name,
                base_url=model_base_url,
                management_url=management_url,
            )
        if not provision_secret:
            return {
                "ok": False,
                "status": "pending",
                "message": "NewAPI provisioning endpoint is not configured",
                "base_url": model_base_url,
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
                    "token_name": _clean(settings.get("token_name"))
                    or "HappyImage Default",
                },
                timeout=20,
            )
            status_code = int(getattr(response, "status_code", 0) or 0)
            if status_code != 200:
                return self._failed(status_code)
            data = self._response_json(response)
            if (
                not isinstance(data, dict)
                or data.get("ok") is not True
                or not _clean(data.get("token"))
            ):
                return self._failed(
                    message="NewAPI provisioning returned an invalid response"
                )
            return {
                "ok": True,
                "status": "configured",
                "user_id": _clean(data.get("user_id")),
                "token_id": _clean(data.get("token_id")),
                "token": _clean(data.get("token")),
                "base_url": _normalize_url(
                    self._normalize_model_base_url(data.get("base_url") or model_base_url),
                    default=self._normalize_model_base_url(DEFAULT_NEWAPI_URL),
                ),
                "management_url": _normalize_management_url(
                    data.get("management_url")
                    or management_url
                    or data.get("base_url")
                    or base_url,
                )
                or DEFAULT_NEWAPI_URL,
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

    def _make_sql_connection(self, dsn: str) -> Any:
        if self._sql_connect_factory is not None:
            return self._sql_connect_factory(dsn)

        import psycopg2

        return psycopg2.connect(dsn)

    def _ensure_default_token_via_sql(
        self,
        *,
        settings: dict[str, object],
        provider: str,
        subject: str,
        email: str,
        name: str,
        base_url: str,
        management_url: str,
    ) -> dict[str, object]:
        dsn = _clean(settings.get("sql_dsn"))
        if not dsn:
            return self._failed(message="NewAPI SQL DSN is not configured")

        connection = None
        try:
            connection = self._make_sql_connection(dsn)
            with connection:
                with connection.cursor() as cursor:
                    user_id = self._find_or_create_newapi_user(
                        cursor,
                        provider=provider,
                        subject=subject,
                        email=email,
                        name=name,
                    )
                    token_id, token = self._find_or_create_newapi_token(
                        cursor,
                        user_id=user_id,
                        token_name=_clean(settings.get("token_name"))
                        or "HappyImage Default",
                    )
                    access_token = self._ensure_newapi_access_token(cursor, user_id)
                    tokens = self._list_newapi_tokens(cursor, user_id)
            return {
                "ok": True,
                "status": "configured",
                "user_id": str(user_id),
                "token_id": str(token_id),
                "token": f"sk-{token}",
                "access_token": access_token,
                "tokens": tokens,
                "base_url": base_url,
                "management_url": management_url,
            }
        except Exception as exc:
            logger.warning(
                {
                    "event": "newapi_sql_provisioning_failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "dsn": self._redact_dsn(dsn),
                }
            )
            return self._failed(message="NewAPI SQL provisioning request failed")
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    @staticmethod
    def _find_or_create_newapi_user(
        cursor: Any,
        *,
        provider: str,
        subject: str,
        email: str,
        name: str,
    ) -> int:
        provider_column = NewAPIBindingService._provider_column(provider)
        cleaned_subject = _clean(subject)
        cleaned_email = _clean(email)
        cleaned_name = _clean(name)
        if provider_column and cleaned_subject:
            cursor.execute(
                f"SELECT id FROM users WHERE {provider_column} = %s AND deleted_at IS NULL ORDER BY id LIMIT 1",
                (cleaned_subject,),
            )
            row = cursor.fetchone()
            if row:
                return int(row[0])
        if cleaned_email:
            cursor.execute(
                "SELECT id FROM users WHERE email = %s AND deleted_at IS NULL ORDER BY id LIMIT 1",
                (cleaned_email,),
            )
            row = cursor.fetchone()
            if row:
                user_id = int(row[0])
                if provider_column and cleaned_subject:
                    cursor.execute(
                        f"UPDATE users SET {provider_column} = COALESCE(NULLIF({provider_column}, ''), %s) WHERE id = %s",
                        (cleaned_subject, user_id),
                    )
                return user_id

        username = NewAPIBindingService._newapi_username(cleaned_email, cleaned_subject)
        display_name = cleaned_name or username
        now = int(time.time())
        password = secrets.token_urlsafe(32)
        access_token = secrets.token_hex(16)
        columns = [
            "username",
            "password",
            "display_name",
            "role",
            "status",
            "email",
            "access_token",
            "quota",
            "used_quota",
            "request_count",
            '"group"',
            "created_at",
            "last_login_at",
        ]
        values: list[object] = [
            username,
            password,
            display_name,
            1,
            1,
            cleaned_email,
            access_token,
            0,
            0,
            0,
            "default",
            now,
            now,
        ]
        if provider_column and cleaned_subject:
            columns.append(provider_column)
            values.append(cleaned_subject)
        placeholders = ", ".join(["%s"] * len(values))
        cursor.execute(
            f"INSERT INTO users ({', '.join(columns)}) VALUES ({placeholders}) RETURNING id",
            values,
        )
        row = cursor.fetchone()
        return int(row[0])

    @staticmethod
    def _find_or_create_newapi_token(
        cursor: Any,
        *,
        user_id: int,
        token_name: str,
    ) -> tuple[int, str]:
        cursor.execute(
            """
            SELECT id, key FROM tokens
            WHERE user_id = %s AND name = %s AND status = 1 AND deleted_at IS NULL
            ORDER BY id
            LIMIT 1
            """,
            (user_id, token_name),
        )
        row = cursor.fetchone()
        if row:
            return int(row[0]), _clean(row[1])

        now = int(time.time())
        token = secrets.token_urlsafe(36)
        cursor.execute(
            """
            INSERT INTO tokens (
                user_id, key, status, name, created_time, accessed_time,
                expired_time, remain_quota, unlimited_quota,
                model_limits_enabled, model_limits, allow_ips, used_quota,
                "group", cross_group_retry
            )
            VALUES (%s, %s, 1, %s, %s, %s, -1, 0, true, false, '', '', 0, '', false)
            RETURNING id
            """,
            (user_id, token, token_name, now, now),
        )
        row = cursor.fetchone()
        return int(row[0]), token

    @staticmethod
    def _ensure_newapi_access_token(cursor: Any, user_id: int) -> str:
        cursor.execute("SELECT access_token FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        access_token = _clean(row[0] if row else "")
        if access_token:
            return access_token
        access_token = secrets.token_hex(16)
        cursor.execute(
            "UPDATE users SET access_token = %s WHERE id = %s",
            (access_token, user_id),
        )
        return access_token

    @staticmethod
    def _list_newapi_tokens(cursor: Any, user_id: int) -> list[dict[str, object]]:
        cursor.execute(
            """
            SELECT id, key, status, name, created_time, accessed_time,
                   expired_time, remain_quota, unlimited_quota, used_quota
            FROM tokens
            WHERE user_id = %s AND deleted_at IS NULL
            ORDER BY id
            """,
            (user_id,),
        )
        tokens = []
        for row in cursor.fetchall():
            key = _clean(row[1])
            tokens.append(
                {
                    "id": int(row[0]),
                    "key": f"sk-{key}" if key and not key.startswith("sk-") else key,
                    "status": int(row[2] or 0),
                    "name": _clean(row[3]),
                    "created_time": int(row[4] or 0),
                    "accessed_time": int(row[5] or 0),
                    "expired_time": int(row[6] or 0),
                    "remain_quota": int(row[7] or 0),
                    "unlimited_quota": bool(row[8]),
                    "used_quota": int(row[9] or 0),
                }
            )
        return tokens

    @staticmethod
    def _provider_column(provider: str) -> str:
        normalized = _clean(provider).lower()
        return {
            "casdoor": "oidc_id",
            "oidc": "oidc_id",
            "github": "github_id",
            "discord": "discord_id",
            "telegram": "telegram_id",
            "wechat": "wechat_id",
            "linuxdo": "linux_do_id",
            "linux_do": "linux_do_id",
        }.get(normalized, "")

    @staticmethod
    def _newapi_username(email: str, subject: str) -> str:
        base = email.split("@", 1)[0] if email else subject
        normalized = "".join(
            char.lower() if char.isalnum() else "-"
            for char in (base or "happyimage-user")
        ).strip("-")
        suffix = secrets.token_hex(4)
        return f"{(normalized or 'happyimage-user')[:40]}-{suffix}"[:64]

    @staticmethod
    def _load_settings() -> dict[str, object]:
        from services.config import config

        return config.get_newapi_binding_settings()

    @staticmethod
    def _normalize_model_base_url(value: object) -> str:
        base_url = _clean(value).rstrip("/")
        if not base_url:
            return ""
        if base_url.endswith("/v1"):
            return base_url
        return f"{base_url}/v1"

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
    def _redact_dsn(dsn: str) -> str:
        try:
            parsed = urlsplit(dsn)
            netloc = parsed.hostname or ""
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            if parsed.username:
                netloc = f"{parsed.username}:***@{netloc}"
            return urlunsplit(
                (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
            )
        except Exception:
            return "<redacted>"

    @staticmethod
    def _failed(
        http_status: int | None = None, *, message: str | None = None
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "ok": False,
            "status": "failed",
            "message": message or "NewAPI provisioning failed",
        }
        if http_status is not None:
            result["http_status"] = http_status
        return result


newapi_binding_service = NewAPIBindingService()
