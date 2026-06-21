from __future__ import annotations

from typing import Any

from services.config import config


class ModelGatewayConfigurationError(RuntimeError):
    pass


def _clean(value: object) -> str:
    return str(value or "").strip()


def is_required() -> bool:
    return bool(config.require_model_gateway)


def is_enabled() -> bool:
    return bool(config.model_gateway_base_url and config.model_gateway_api_key)


def ensure_available() -> None:
    if is_required() and not is_enabled():
        raise ModelGatewayConfigurationError("model gateway is not configured")


def _request_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    from curl_cffi import requests

    url = f"{config.model_gateway_base_url}{path}"
    session = requests.Session()
    try:
        response = session.post(
            url,
            headers={
                "Authorization": f"Bearer {config.model_gateway_api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
            timeout=300,
        )
        data = response.json() if response.text else {}
    finally:
        session.close()
    if response.status_code >= 400 or not isinstance(data, dict):
        detail = ""
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                detail = _clean(error.get("message"))
            else:
                detail = _clean(error)
        raise RuntimeError(detail or f"model gateway rejected request (HTTP {response.status_code})")
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
    return _request_json("/images/generations", body)


def edit_image(payload: dict[str, Any]) -> dict[str, Any]:
    from curl_cffi import requests

    url = f"{config.model_gateway_base_url}/images/edits"
    data: dict[str, str] = {
        "model": _clean(payload.get("model")) or "gpt-image-2",
        "prompt": _clean(payload.get("prompt")),
        "n": str(int(payload.get("n") or 1)),
        "quality": _clean(payload.get("quality")) or "auto",
        "response_format": _clean(payload.get("response_format")) or "url",
    }
    if payload.get("size"):
        data["size"] = _clean(payload.get("size"))
    files = [
        ("image", (filename, content, mime_type))
        for content, filename, mime_type in (payload.get("images") or [])
    ]
    if not files:
        raise RuntimeError("image is required")

    session = requests.Session()
    try:
        response = session.post(
            url,
            headers={
                "Authorization": f"Bearer {config.model_gateway_api_key}",
                "Accept": "application/json",
            },
            data=data,
            files=files,
            timeout=300,
        )
        result = response.json() if response.text else {}
    finally:
        session.close()
    if response.status_code >= 400 or not isinstance(result, dict):
        detail = ""
        if isinstance(result, dict):
            error = result.get("error")
            if isinstance(error, dict):
                detail = _clean(error.get("message"))
            else:
                detail = _clean(error)
        raise RuntimeError(detail or f"model gateway rejected request (HTTP {response.status_code})")
    return result
