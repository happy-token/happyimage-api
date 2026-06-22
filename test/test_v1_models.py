from __future__ import annotations

from services.protocol import openai_v1_models


def test_list_models_returns_static_image_models():
    result = openai_v1_models.list_models()

    assert result["object"] == "list"
    ids = {item["id"] for item in result["data"]}
    assert "gpt-image-2" in ids
    assert "codex-gpt-image-2" in ids
