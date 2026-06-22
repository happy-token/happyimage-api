from __future__ import annotations

from typing import Any

MODEL_GATEWAY_MAX_ATTEMPTS = 2


class ModelGatewayConfigurationError(RuntimeError):
    pass


def _clean(value: object) -> str:
    return str(value or "").strip()


def humanize_gateway_error(error: object) -> str:
    message = _clean(error)
    lowered = message.lower()
    if not message:
        return "图片生成失败，请稍后重试。"
    if "model gateway is not configured" in lowered:
        return "请先在用户设置中配置模型供应商 Base URL 和 API Key。"
    if any(marker in lowered for marker in ("insufficient_quota", "quota", "credit", "credits", "balance", "billing", "payment required", "recharge", "余额", "额度", "欠费")):
        return "模型供应商额度不足，请先充值或更换供应商后再试。"
    if any(marker in lowered for marker in ("401", "unauthorized", "invalid api key", "incorrect api key", "invalid token", "api key is invalid", "apikey")):
        return "模型供应商 API Key 无效或已过期，请在用户设置里更新 API Key。"
    if any(marker in lowered for marker in ("model not found", "invalid model", "does not exist", "unsupported model")):
        return "当前模型不可用，请在生图页面切换可用模型后再试。"
    if any(marker in lowered for marker in ("timeout", "timed out", "read timed out")):
        return "模型供应商响应超时，请稍后重试。"
    if any(
        marker in lowered
        for marker in (
            "curl:",
            "tls connect error",
            "openssl",
            "connection closed abruptly",
            "connection reset",
            "empty reply from server",
            "server disconnected",
            "connection aborted",
        )
    ):
        return "连接模型供应商失败，请稍后重试；如果持续出现，请检查 Base URL 或网络代理。"
    if any(marker in lowered for marker in ("no image", "no data", "returned empty", "没有返回图片")):
        return "模型供应商没有返回图片结果，请换个提示词或稍后重试。"
    return message


def is_enabled(base_url: str = "", api_key: str = "") -> bool:
    return bool(_clean(base_url) and _clean(api_key))


def ensure_available(base_url: str = "", api_key: str = "") -> None:
    if not is_enabled(base_url, api_key):
        raise ModelGatewayConfigurationError(humanize_gateway_error("model gateway is not configured"))


def _gateway_base_url(payload: dict[str, Any]) -> str:
    return _clean(payload.get("model_gateway_base_url"))


def _gateway_api_key(payload: dict[str, Any]) -> str:
    return _clean(payload.get("model_gateway_api_key"))


def _is_retryable_gateway_error(error: Exception) -> bool:
    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "curl: (35)",
            "curl: (52)",
            "curl: (56)",
            "tls connect error",
            "empty reply from server",
            "connection closed abruptly",
            "connection reset",
            "server disconnected",
        )
    )


def _request_json(path: str, payload: dict[str, Any], gateway_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    import requests

    gateway_source = gateway_payload or payload
    base_url = _gateway_base_url(gateway_source)
    api_key = _gateway_api_key(gateway_source)
    if not base_url or not api_key:
        raise ModelGatewayConfigurationError(humanize_gateway_error("model gateway is not configured"))
    url = f"{base_url}{path}"
    last_error: Exception | None = None
    for attempt in range(MODEL_GATEWAY_MAX_ATTEMPTS):
        session = requests.Session()
        try:
            response = session.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
                timeout=300,
            )
            data = response.json() if response.text else {}
            break
        except Exception as exc:
            last_error = exc
            if attempt >= MODEL_GATEWAY_MAX_ATTEMPTS - 1 or not _is_retryable_gateway_error(exc):
                raise RuntimeError(humanize_gateway_error(exc)) from exc
        finally:
            session.close()
    else:
        raise last_error or RuntimeError("model gateway request failed")
    if response.status_code >= 400 or not isinstance(data, dict):
        detail = ""
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                detail = _clean(error.get("message"))
            else:
                detail = _clean(error)
        raise RuntimeError(humanize_gateway_error(detail or f"model gateway rejected request (HTTP {response.status_code})"))
    return data


def generate_image(payload: dict[str, Any]) -> dict[str, Any]:
    body = {
        "model": _clean(payload.get("model")) or "gpt-image-2",
        "prompt": _clean(payload.get("prompt")),
        "n": int(payload.get("n") or 1),
        "quality": _clean(payload.get("quality")) or "auto",
        "response_format": _clean(payload.get("response_format")) or "url",
    }
    if payload.get("size"):
        body["size"] = payload.get("size")
    return _request_json("/images/generations", body, payload)


def edit_image(payload: dict[str, Any]) -> dict[str, Any]:
    import requests

    base_url = _gateway_base_url(payload)
    api_key = _gateway_api_key(payload)
    if not base_url or not api_key:
        raise ModelGatewayConfigurationError(humanize_gateway_error("model gateway is not configured"))
    url = f"{base_url}/images/edits"
    fields: dict[str, str] = {
        "model": _clean(payload.get("model")) or "gpt-image-2",
        "prompt": _clean(payload.get("prompt")),
        "n": str(int(payload.get("n") or 1)),
        "quality": _clean(payload.get("quality")) or "auto",
        "response_format": _clean(payload.get("response_format")) or "url",
    }
    if payload.get("size"):
        fields["size"] = _clean(payload.get("size"))
    images = [
        (content, filename, mime_type)
        for content, filename, mime_type in (payload.get("images") or [])
    ]
    if not images:
        raise RuntimeError("image is required")

    last_error: Exception | None = None
    for attempt in range(MODEL_GATEWAY_MAX_ATTEMPTS):
        session = requests.Session()
        try:
            response = session.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                },
                data=fields,
                files=[
                    ("image", (filename, content, mime_type or "application/octet-stream"))
                    for content, filename, mime_type in images
                ],
                timeout=300,
            )
            result = response.json() if response.text else {}
            break
        except Exception as exc:
            last_error = exc
            if attempt >= MODEL_GATEWAY_MAX_ATTEMPTS - 1 or not _is_retryable_gateway_error(exc):
                raise RuntimeError(humanize_gateway_error(exc)) from exc
        finally:
            session.close()
    else:
        raise last_error or RuntimeError("model gateway request failed")
    if response.status_code >= 400 or not isinstance(result, dict):
        detail = ""
        if isinstance(result, dict):
            error = result.get("error")
            if isinstance(error, dict):
                detail = _clean(error.get("message"))
            else:
                detail = _clean(error)
        raise RuntimeError(humanize_gateway_error(detail or f"model gateway rejected request (HTTP {response.status_code})"))
    return result
