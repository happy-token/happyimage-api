from __future__ import annotations

from typing import Any

from utils.helper import CODEX_IMAGE_MODEL


def _model_item(model: str) -> dict[str, Any]:
    return {
        "id": model,
        "object": "model",
        "created": 0,
        "owned_by": "happytoken",
        "permission": [],
        "root": model,
        "parent": None,
    }


def _image_models() -> list[str]:
    return ["gpt-image-2", CODEX_IMAGE_MODEL]


def list_models() -> dict[str, Any]:
    return {"object": "list", "data": [_model_item(model) for model in _image_models()]}
