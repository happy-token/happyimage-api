from __future__ import annotations

import base64
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from services.config import DATA_DIR, config
from services.content_filter import request_text
from services.image_storage_service import image_storage_service
from services.image_task_store import ImageTaskStore, JSONImageTaskStore, create_image_task_store
from services.log_service import LOG_TYPE_CALL, log_service

TASK_STATUS_QUEUED = "queued"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_SUCCESS = "success"
TASK_STATUS_ERROR = "error"
TERMINAL_STATUSES = {TASK_STATUS_SUCCESS, TASK_STATUS_ERROR}
UNFINISHED_STATUSES = {TASK_STATUS_QUEUED, TASK_STATUS_RUNNING}


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _timestamp(value: object) -> float:
    if not isinstance(value, str) or not value.strip():
        return 0.0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:26], fmt).timestamp()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _clean(value: object, default: str = "") -> str:
    return str(value or default).strip()


def _owner_id(identity: dict[str, object]) -> str:
    return _clean(identity.get("id")) or "anonymous"


def _identity_model_gateway(identity: dict[str, object]) -> dict[str, object]:
    base_url = _clean(identity.get("model_base_url")).rstrip("/")
    api_key = _clean(identity.get("model_api_key"))
    if not base_url or not api_key:
        return {}
    return {
        "model_gateway_provider": _clean(identity.get("model_provider")) or "newapi",
        "model_gateway_base_url": base_url,
        "model_gateway_api_key": api_key,
    }


def _task_key(owner_id: str, task_id: str) -> str:
    return f"{owner_id}:{task_id}"


def _collect_image_urls(data: list[Any]) -> list[str]:
    urls: list[str] = []
    for item in data:
        if isinstance(item, dict):
            url = item.get("url")
            if isinstance(url, str) and url:
                urls.append(url)
    return urls


def _is_http_url(value: str) -> bool:
    try:
        return urlparse(value).scheme in {"http", "https"}
    except Exception:
        return False


def _is_own_image_url(value: str, base_url: str) -> bool:
    normalized_base = _clean(base_url or config.base_url).rstrip("/")
    return bool(normalized_base and value.startswith(f"{normalized_base}/images/"))


def _download_remote_image(url: str) -> bytes:
    from curl_cffi import requests

    session = requests.Session()
    try:
        response = session.get(url, timeout=120, impersonate="chrome")
        if response.status_code >= 400:
            raise RuntimeError(f"image download failed (HTTP {response.status_code})")
        payload = bytes(response.content or b"")
    finally:
        session.close()
    if not payload:
        raise RuntimeError("image download returned empty response")
    return payload


def _materialize_gateway_images(data: list[Any], *, base_url: str, owner_id: str) -> list[Any]:
    materialized: list[Any] = []
    for entry in data:
        if not isinstance(entry, dict):
            materialized.append(entry)
            continue
        item = dict(entry)
        image_data: bytes | None = None
        b64_json = _clean(item.get("b64_json"))
        url = _clean(item.get("url"))
        if b64_json:
            try:
                image_data = base64.b64decode(b64_json)
            except Exception as exc:
                raise RuntimeError("gateway returned invalid base64 image data") from exc
        elif url and _is_http_url(url) and not _is_own_image_url(url, base_url):
            image_data = _download_remote_image(url)
            item["source_url"] = url
        if image_data is not None:
            stored = image_storage_service.save(image_data, base_url=base_url, owner_id=owner_id)
            item["url"] = stored.url
            item["path"] = stored.rel
            item["storage"] = stored.storage
            item.pop("b64_json", None)
        materialized.append(item)
    return materialized


def _normalize_feedback(value: object) -> str | None:
    if value in ("like", "dislike"):
        return str(value)
    return None


def _feedback_summary(feedback: object, image_index: int) -> dict[str, Any] | None:
    if not isinstance(feedback, dict):
        return None
    item = feedback.get(str(image_index))
    if not isinstance(item, dict):
        return None
    vote = _normalize_feedback(item.get("vote"))
    return {
        "vote": vote,
        "likes": 1 if vote == "like" else 0,
        "dislikes": 1 if vote == "dislike" else 0,
        "updated_at": _clean(item.get("updated_at")),
    }


def _public_task(task: dict[str, Any]) -> dict[str, Any]:
    item = {
        "id": task.get("id"),
        "status": task.get("status"),
        "mode": task.get("mode"),
        "model": task.get("model"),
        "size": task.get("size"),
        "quality": task.get("quality"),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
    }
    if task.get("prompt"):
        item["prompt"] = task.get("prompt")
    if task.get("conversation_id"):
        item["conversation_id"] = task.get("conversation_id")
    if task.get("client_conversation_id"):
        item["client_conversation_id"] = task.get("client_conversation_id")
    if task.get("client_turn_id"):
        item["client_turn_id"] = task.get("client_turn_id")
    if task.get("client_image_id"):
        item["client_image_id"] = task.get("client_image_id")
    if task.get("data") is not None:
        data = task.get("data")
        if isinstance(data, list):
            public_data = []
            for index, entry in enumerate(data):
                if isinstance(entry, dict):
                    public_entry = dict(entry)
                    summary = _feedback_summary(task.get("feedback"), index)
                    if summary:
                        public_entry["feedback"] = summary
                    public_data.append(public_entry)
                else:
                    public_data.append(entry)
            item["data"] = public_data
        else:
            item["data"] = data
    if task.get("usage") is not None:
        item["usage"] = task.get("usage")
    if task.get("error"):
        item["error"] = task.get("error")
    if task.get("progress"):
        item["progress"] = task.get("progress")
    if task.get("duration_ms") is not None:
        item["duration_ms"] = task.get("duration_ms")
    if task.get("status") in (TASK_STATUS_RUNNING, TASK_STATUS_QUEUED):
        if task.get("status") == TASK_STATUS_RUNNING:
            # RUNNING 状态仅在 started_ts 被设置后（image_stream_resolve_start）才计时
            base_ts = task.get("started_ts")
        else:
            # QUEUED 状态从 created_ts 开始计时（排队等待中）
            base_ts = task.get("created_ts") or task.get("updated_ts")
        if base_ts:
            item["elapsed_secs"] = round(time.time() - base_ts, 1)
    return item


class ImageTaskService:
    def __init__(
        self,
        path: Path,
        *,
        generation_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        edit_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        retention_days_getter: Callable[[], int] | None = None,
        task_store: ImageTaskStore | None = None,
    ):
        self.path = path
        self.generation_handler = generation_handler
        self.edit_handler = edit_handler
        self.retention_days_getter = retention_days_getter or (lambda: config.image_retention_days)
        self.task_store = task_store or create_image_task_store(path)
        self._migrated_from_json = False
        self._lock = threading.RLock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._tasks = self._load_locked()
            changed = self._recover_unfinished_locked()
            changed = self._cleanup_locked() or changed
            changed = self._migrated_from_json or changed
            if changed:
                self._save_locked()

    def submit_generation(
        self,
        identity: dict[str, object],
        *,
        client_task_id: str,
        prompt: str,
        model: str,
        size: str | None,
        quality: str = "auto",
        base_url: str = "",
        client_conversation_id: str = "",
        client_turn_id: str = "",
        client_image_id: str = "",
    ) -> dict[str, Any]:
        payload = {
            "prompt": prompt,
            "model": model,
            "n": 1,
            "size": size,
            "quality": quality,
            "response_format": "url",
            "base_url": base_url,
            "owner_id": _owner_id(identity),
            "client_conversation_id": client_conversation_id,
            "client_turn_id": client_turn_id,
            "client_image_id": client_image_id,
            **_identity_model_gateway(identity),
        }
        return self._submit(identity, client_task_id=client_task_id, mode="generate", payload=payload)

    def submit_edit(
        self,
        identity: dict[str, object],
        *,
        client_task_id: str,
        prompt: str,
        model: str,
        size: str | None,
        quality: str = "auto",
        base_url: str = "",
        images: list[tuple[bytes, str, str]] | None = None,
        client_conversation_id: str = "",
        client_turn_id: str = "",
        client_image_id: str = "",
    ) -> dict[str, Any]:
        payload = {
            "prompt": prompt,
            "images": images or [],
            "model": model,
            "n": 1,
            "size": size,
            "quality": quality,
            "response_format": "url",
            "base_url": base_url,
            "owner_id": _owner_id(identity),
            "client_conversation_id": client_conversation_id,
            "client_turn_id": client_turn_id,
            "client_image_id": client_image_id,
            **_identity_model_gateway(identity),
        }
        return self._submit(identity, client_task_id=client_task_id, mode="edit", payload=payload)

    def list_tasks(self, identity: dict[str, object], task_ids: list[str]) -> dict[str, Any]:
        owner = _owner_id(identity)
        requested_ids = [_clean(task_id) for task_id in task_ids if _clean(task_id)]
        with self._lock:
            if self._cleanup_locked():
                self._save_locked()
            items = []
            missing_ids = []
            for task_id in requested_ids:
                task = self._tasks.get(_task_key(owner, task_id))
                if task is None:
                    missing_ids.append(task_id)
                else:
                    items.append(_public_task(task))
            if not requested_ids:
                items = [
                    _public_task(task)
                    for task in self._tasks.values()
                    if task.get("owner_id") == owner
                ]
                items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
                missing_ids = []
            return {"items": items, "missing_ids": missing_ids}

    def set_image_feedback(
        self,
        identity: dict[str, object],
        *,
        task_id: str,
        image_index: int,
        vote: str | None,
    ) -> dict[str, Any]:
        owner = _owner_id(identity)
        normalized_task_id = _clean(task_id)
        if not normalized_task_id:
            raise ValueError("task_id is required")
        if image_index < 0:
            raise ValueError("image_index is invalid")
        normalized_vote = _normalize_feedback(vote)
        if vote is not None and normalized_vote is None:
            raise ValueError("vote is invalid")

        key = _task_key(owner, normalized_task_id)
        with self._lock:
            task = self._tasks.get(key)
            if task is None:
                raise ValueError("task not found")
            data = task.get("data")
            if not isinstance(data, list) or image_index >= len(data):
                raise ValueError("image not found")
            feedback = task.get("feedback")
            if not isinstance(feedback, dict):
                feedback = {}
            feedback_key = str(image_index)
            if normalized_vote is None:
                feedback.pop(feedback_key, None)
            else:
                feedback[feedback_key] = {
                    "vote": normalized_vote,
                    "updated_at": _now_iso(),
                }
            if feedback:
                task["feedback"] = feedback
            else:
                task.pop("feedback", None)
            task["updated_at"] = _now_iso()
            task["updated_ts"] = time.time()
            self._save_locked()
            return _public_task(task)

    def _submit(
        self,
        identity: dict[str, object],
        *,
        client_task_id: str,
        mode: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        task_id = _clean(client_task_id)
        if not task_id:
            raise ValueError("client_task_id is required")
        owner = _owner_id(identity)
        key = _task_key(owner, task_id)
        now = _now_iso()
        should_start = False
        with self._lock:
            cleaned = self._cleanup_locked()
            task = self._tasks.get(key)
            if task is not None:
                if cleaned:
                    self._save_locked()
                return _public_task(task)
            task = {
                "id": task_id,
                "owner_id": owner,
                "status": TASK_STATUS_QUEUED,
                "mode": mode,
                "prompt": _clean(payload.get("prompt")),
                "model": _clean(payload.get("model"), "gpt-image-2"),
                "size": _clean(payload.get("size")),
                "quality": _clean(payload.get("quality"), "auto"),
                "created_at": now,
                "updated_at": now,
                "created_ts": time.time(),
            }
            client_conversation_id = _clean(payload.get("client_conversation_id"))
            client_turn_id = _clean(payload.get("client_turn_id"))
            client_image_id = _clean(payload.get("client_image_id"))
            if client_conversation_id:
                task["client_conversation_id"] = client_conversation_id
            if client_turn_id:
                task["client_turn_id"] = client_turn_id
            if client_image_id:
                task["client_image_id"] = client_image_id
            try:
                self._tasks[key] = task
                self._save_locked()
            except Exception:
                self._tasks.pop(key, None)
                raise
            should_start = True
            public_task = _public_task(task)

        if should_start:
            thread = threading.Thread(
                target=self._run_task,
                args=(key, mode, payload, dict(identity), _clean(payload.get("model"), "gpt-image-2")),
                name=f"image-task-{task_id[:16]}",
                daemon=True,
            )
            thread.start()
        return public_task

    def _run_task(
        self,
        key: str,
        mode: str,
        payload: dict[str, Any],
        identity: dict[str, object],
        model: str,
    ) -> None:
        started = time.time()
        self._update_task(key, status=TASK_STATUS_RUNNING, error="")
        with self._lock:
            current_task = dict(self._tasks.get(key) or {})
        self._update_linked_result(identity, current_task, {"status": "loading", "taskStatus": "running"})
        # 创建进度回调，每个步骤完成后更新任务状态
        def progress_callback(step: str) -> None:
            if step == "image_stream_resolve_start":
                self._update_task(key, started_ts=time.time())
            self._update_task(key, progress=step)
        # 将进度回调添加到 payload 中，供网关实现按需更新任务状态。
        payload_with_progress = {**payload, "progress_callback": progress_callback}
        try:
            from services import model_gateway_service

            gateway_base_url = _clean(payload_with_progress.get("model_gateway_base_url"))
            gateway_api_key = _clean(payload_with_progress.get("model_gateway_api_key"))
            model_gateway_service.ensure_available(gateway_base_url, gateway_api_key)
            result = (
                model_gateway_service.edit_image(payload_with_progress)
                if mode == "edit"
                else model_gateway_service.generate_image(payload_with_progress)
            )
            if not isinstance(result, dict):
                raise RuntimeError("image task returned streaming result unexpectedly")
            data = result.get("data")
            account_email = _clean(result.get("_account_email") or result.get("account_email"))
            if not isinstance(data, list) or not data:
                upstream = _clean(result.get("message"))
                if upstream:
                    message = upstream
                else:
                    message = "模型供应商没有返回图片结果，请检查用户设置中的 Base URL、API Key 和模型配置"
                error = RuntimeError(message)
                if account_email:
                    setattr(error, "account_email", account_email)
                raise error
            data = _materialize_gateway_images(
                data,
                base_url=_clean(payload.get("base_url")),
                owner_id=_owner_id(identity),
            )
            usage = result.get("usage")
            duration_ms = int((time.time() - started) * 1000)
            self._update_task(key, status=TASK_STATUS_SUCCESS, data=data, usage=usage, error="", duration_ms=duration_ms)
            with self._lock:
                current_task = dict(self._tasks.get(key) or {})
            first = data[0] if data and isinstance(data[0], dict) else {}
            self._update_linked_result(
                identity,
                current_task,
                {
                    "status": "success",
                    "taskStatus": None,
                    "progress": None,
                    "error": None,
                    "url": first.get("url"),
                    "revised_prompt": first.get("revised_prompt"),
                    "durationMs": duration_ms,
                },
            )
            self._log_call(
                identity,
                mode,
                model,
                started,
                "调用完成",
                request_preview=request_text(payload.get("prompt")),
                urls=_collect_image_urls(data),
                account_email=account_email,
            )
        except Exception as exc:
            from services.model_gateway_service import humanize_gateway_error

            error_message = humanize_gateway_error(str(exc) or "image task failed")
            account_email = _clean(getattr(exc, "account_email", ""))
            conversation_id = _clean(getattr(exc, "conversation_id", ""))
            duration_ms = int((time.time() - started) * 1000)
            self._update_task(key, status=TASK_STATUS_ERROR, error=error_message, data=[],
                              duration_ms=duration_ms,
                              **({"conversation_id": conversation_id} if conversation_id else {}))
            with self._lock:
                current_task = dict(self._tasks.get(key) or {})
            self._update_linked_result(
                identity,
                current_task,
                {
                    "status": "error",
                    "taskStatus": None,
                    "progress": None,
                    "error": error_message,
                    "durationMs": duration_ms,
                },
            )
            self._log_call(
                identity,
                mode,
                model,
                started,
                "调用失败",
                request_preview=request_text(payload.get("prompt")),
                status="failed",
                error=error_message,
                account_email=account_email,
            )

    def _log_call(
        self,
        identity: dict[str, object],
        mode: str,
        model: str,
        started: float,
        suffix: str,
        *,
        request_preview: str = "",
        status: str = "success",
        error: str = "",
        urls: list[str] | None = None,
        account_email: str = "",
    ) -> None:
        endpoint = "/v1/images/edits" if mode == "edit" else "/v1/images/generations"
        summary_prefix = "图生图" if mode == "edit" else "文生图"
        detail = {
            "key_id": identity.get("id"),
            "key_name": identity.get("name"),
            "role": identity.get("role"),
            "endpoint": endpoint,
            "model": model,
            "started_at": datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M:%S"),
            "ended_at": _now_iso(),
            "duration_ms": int((time.time() - started) * 1000),
            "status": status,
        }
        if request_preview:
            detail["request_text"] = request_preview
        if error:
            detail["error"] = error
        if account_email:
            detail["account_email"] = account_email
        if urls:
            detail["urls"] = list(dict.fromkeys(urls))
        try:
            log_service.add(LOG_TYPE_CALL, f"{summary_prefix}{suffix}", detail)
        except Exception:
            pass

    def _update_task(self, key: str, **updates: Any) -> None:
        with self._lock:
            task = self._tasks.get(key)
            if task is None:
                return
            task.update(updates)
            task["updated_at"] = _now_iso()
            task["updated_ts"] = time.time()
            self._save_locked()

    def _conversation_link(self, task: dict[str, Any]) -> tuple[str, str]:
        return _clean(task.get("client_conversation_id")), _clean(task.get("client_image_id"))

    def _update_linked_result(self, identity: dict[str, object], task: dict[str, Any], updates: dict[str, Any]) -> None:
        conversation_id, image_id = self._conversation_link(task)
        if not conversation_id or not image_id:
            return
        try:
            from services.image_conversation_service import image_conversation_service

            image_conversation_service.update_result(
                identity,
                conversation_id=conversation_id,
                image_id=image_id,
                updates=updates,
            )
        except Exception:
            pass

    def _load_locked(self) -> dict[str, dict[str, Any]]:
        raw_items = self.task_store.load_tasks()
        if not raw_items and not isinstance(self.task_store, JSONImageTaskStore) and self.path.exists():
            raw_items = JSONImageTaskStore(self.path).load_tasks()
            self._migrated_from_json = bool(raw_items)
        if not isinstance(raw_items, list):
            return {}
        tasks: dict[str, dict[str, Any]] = {}
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            task_id = _clean(item.get("id"))
            owner = _clean(item.get("owner_id"))
            if not task_id or not owner:
                continue
            status = _clean(item.get("status"))
            if status not in {TASK_STATUS_QUEUED, TASK_STATUS_RUNNING, TASK_STATUS_SUCCESS, TASK_STATUS_ERROR}:
                status = TASK_STATUS_ERROR
            task = {
                "id": task_id,
                "owner_id": owner,
                "status": status,
                "mode": "edit" if item.get("mode") == "edit" else "generate",
                "prompt": _clean(item.get("prompt")),
                "model": _clean(item.get("model"), "gpt-image-2"),
                "size": _clean(item.get("size")),
                "quality": _clean(item.get("quality"), "auto"),
                "created_at": _clean(item.get("created_at"), _now_iso()),
                "updated_at": _clean(item.get("updated_at"), _clean(item.get("created_at"), _now_iso())),
                "created_ts": item.get("created_ts"),
                "updated_ts": item.get("updated_ts"),
                "started_ts": item.get("started_ts"),
                "duration_ms": item.get("duration_ms"),
            }
            conversation_id = _clean(item.get("conversation_id"))
            client_conversation_id = _clean(item.get("client_conversation_id"))
            client_turn_id = _clean(item.get("client_turn_id"))
            client_image_id = _clean(item.get("client_image_id"))
            if conversation_id:
                task["conversation_id"] = conversation_id
            if client_conversation_id:
                task["client_conversation_id"] = client_conversation_id
            if client_turn_id:
                task["client_turn_id"] = client_turn_id
            if client_image_id:
                task["client_image_id"] = client_image_id
            data = item.get("data")
            if isinstance(data, list):
                task["data"] = data
            usage = item.get("usage")
            if isinstance(usage, dict):
                task["usage"] = usage
            error = _clean(item.get("error"))
            if error:
                task["error"] = error
            feedback = item.get("feedback")
            if isinstance(feedback, dict):
                normalized_feedback: dict[str, dict[str, str]] = {}
                for index, feedback_item in feedback.items():
                    if not isinstance(feedback_item, dict):
                        continue
                    vote = _normalize_feedback(feedback_item.get("vote"))
                    if vote is None:
                        continue
                    normalized_feedback[_clean(index)] = {
                        "vote": vote,
                        "updated_at": _clean(feedback_item.get("updated_at")),
                    }
                if normalized_feedback:
                    task["feedback"] = normalized_feedback
            tasks[_task_key(owner, task_id)] = task
        return tasks

    def _save_locked(self) -> None:
        items = sorted(self._tasks.values(), key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        self.task_store.save_tasks(items)

    def _recover_unfinished_locked(self) -> bool:
        changed = False
        for task in self._tasks.values():
            if task.get("status") in UNFINISHED_STATUSES:
                error_message = "服务已重启，未完成的图片任务已中断"
                task["status"] = TASK_STATUS_ERROR
                task["error"] = error_message
                task["updated_at"] = _now_iso()
                task["updated_ts"] = time.time()
                self._update_linked_result(
                    {"id": task.get("owner_id") or "anonymous"},
                    task,
                    {
                        "status": "error",
                        "taskStatus": None,
                        "progress": None,
                        "error": error_message,
                    },
                )
                changed = True
        return changed

    def _cleanup_locked(self) -> bool:
        try:
            retention_days = max(1, int(self.retention_days_getter()))
        except Exception:
            retention_days = 30
        cutoff = time.time() - retention_days * 86400
        removed_keys = [
            key
            for key, task in self._tasks.items()
            if task.get("status") in TERMINAL_STATUSES and _timestamp(task.get("updated_at")) < cutoff
        ]
        for key in removed_keys:
            self._tasks.pop(key, None)
        return bool(removed_keys)

image_task_service = ImageTaskService(DATA_DIR / "image_tasks.json")
