from __future__ import annotations

import json
from typing import Any

MAX_TITLE_LENGTH = 200
MAX_ORIGINAL_PROMPT_LENGTH = 8000
MAX_MODEL_LENGTH = 100
MAX_SIZE_LENGTH = 50
MAX_QUALITY_LENGTH = 50
MAX_SUMMARY_LENGTH = 4000
MAX_MESSAGES = 40
MAX_MESSAGE_ROLE_LENGTH = 32
MAX_MESSAGE_CONTENT_LENGTH = 4000


def _clean(value: object) -> str:
    return str(value or "").strip()


def _truncate(value: object, max_length: int) -> str:
    return _clean(value)[:max_length]


def _conversation_messages(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    messages = []
    for item in value[:MAX_MESSAGES]:
        if not isinstance(item, dict):
            continue
        role = _truncate(item.get("role"), MAX_MESSAGE_ROLE_LENGTH)
        content = _truncate(item.get("content"), MAX_MESSAGE_CONTENT_LENGTH)
        if role or content:
            messages.append({"role": role, "content": content})
    return messages


def _metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "title": _truncate(payload.get("conversation_title") or payload.get("title"), MAX_TITLE_LENGTH),
        "original_prompt": _truncate(payload.get("original_prompt"), MAX_ORIGINAL_PROMPT_LENGTH),
        "model": _truncate(payload.get("model"), MAX_MODEL_LENGTH),
        "size": _truncate(payload.get("size"), MAX_SIZE_LENGTH),
        "quality": _truncate(payload.get("quality"), MAX_QUALITY_LENGTH),
        "conversation_summary": _truncate(payload.get("conversation_summary"), MAX_SUMMARY_LENGTH),
    }
    messages = _conversation_messages(payload.get("conversation_messages"))
    if messages:
        metadata["conversation_messages"] = messages
    return {key: value for key, value in metadata.items() if value}


def _metadata_text(payload: dict[str, Any]) -> str:
    return json.dumps(_metadata(payload), ensure_ascii=False, indent=2)


def _fallback(payload: dict[str, Any], default: str) -> str:
    return _clean(payload.get("original_prompt")) or default


def _generate(payload: dict[str, Any], fallback: str) -> str:
    metadata = _metadata(payload)
    title = _clean(metadata.get("title"))
    original_prompt = _clean(metadata.get("original_prompt"))
    summary = _clean(metadata.get("conversation_summary"))
    if summary:
        return summary
    if original_prompt:
        return original_prompt
    if title:
        return title
    return _fallback(payload, fallback)


def generate_conversation_summary(payload: dict[str, Any]) -> str:
    return _generate(
        payload,
        "这张图片来自一次图库创作，可围绕画面主题提炼分享内容。",
    )


def generate_share_prompt(payload: dict[str, Any]) -> str:
    return _generate(
        payload,
        "请根据图片内容生成适合分享的中文文案。",
    )
