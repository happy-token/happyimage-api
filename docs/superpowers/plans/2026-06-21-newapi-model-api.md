# NewAPI Model API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make HappyImage's NewAPI-first model flow match the PRD: HappyImage keeps sessions/history/gallery/task state while NewAPI owns model account management and upstream routing.

**Architecture:** Keep `/api/image-tasks/*` as the first-phase lightweight task proxy. The API creates and owns task records, forwards model work to the configured OpenAI-compatible gateway, stores success/error state, and exposes restorable history. `/v1/*` remains the OpenAI-compatible surface for NewAPI/external clients, while local account/debug surfaces stay outside this workflow.

**Tech Stack:** FastAPI, Pydantic, pytest, curl_cffi, Next.js middleware, TypeScript.

---

## File Structure

### happyimage-api

- Modify: `services/image_task_service.py`
  - Public task serialization.
  - Gateway configuration failure behavior.
  - Idempotency and failure-state preservation.
- Modify: `services/model_gateway_service.py`
  - Gateway enabled/configured helpers.
  - Typed gateway configuration error.
- Modify: `services/config.py`
  - Add a deployment flag to require the model gateway for task APIs.
- Modify: `.env.example`
  - Document the strict gateway flag.
- Modify: `README.md`
  - Document the first-phase lightweight task proxy acceptance commands.
- Test: `test/test_image_task_service.py`
  - Unit coverage for metadata, idempotency, gateway missing, gateway failure.
- Test: `test/test_image_tasks_api.py`
  - HTTP contract coverage for `/api/image-tasks/*`.
- Test: `test/test_newapi_gateway_chain.py`
  - Ensure NewAPI-compatible routes stay compatible and `/api/*` remains product-only.

### happyimage-web

- Modify: `src/middleware.ts`
  - Keep `/api/*` and `/v1/*` routing split.
  - Ensure `/v1/*` auth replacement stays server-side.
- Test/Create: `src/middleware.test.ts`
  - Middleware route target and auth replacement tests.
- Modify: `README.md`
  - Keep web env documentation aligned with API README.

---

### Task 1: Make Task API Response Metadata Explicit

**Files:**
- Modify: `services/image_task_service.py`
- Test: `test/test_image_task_service.py`

- [ ] **Step 1: Write the failing test**

Add this test to `test/test_image_task_service.py` near the existing submit/list task tests:

```python
def test_submit_generation_returns_prompt_and_client_task_metadata(self):
    identity = {"id": "user-1", "role": "user", "image_quota": 10}
    service = self.make_service(
        generation_handler=lambda payload: {
            "data": [{"url": "http://example.test/image.png"}],
            "usage": {"total_tokens": 1},
        }
    )

    task = service.submit_generation(
        identity,
        client_task_id="client-001",
        prompt="a clean product photo",
        model="gpt-image-2",
        size="1024x1024",
        quality="auto",
        base_url="http://api.test",
    )

    assert task["id"] == "client-001"
    assert task["status"] == "queued"
    assert task["mode"] == "generate"
    assert task["prompt"] == "a clean product photo"
    assert task["model"] == "gpt-image-2"
    assert task["size"] == "1024x1024"
    assert task["quality"] == "auto"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest -q test/test_image_task_service.py::ImageTaskServiceTests::test_submit_generation_returns_prompt_and_client_task_metadata
```

Expected: fail with `KeyError: 'prompt'` or an assertion showing `prompt` is missing from the public task.

- [ ] **Step 3: Store prompt and expose public metadata**

In `services/image_task_service.py`, update `_public_task` to include prompt when present:

```python
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
```

In `_submit`, add prompt to the created task:

```python
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
    "quota_reserved": quota_reserved,
    "quota_cost": 1,
}
```

- [ ] **Step 4: Run the focused test**

Run:

```bash
uv run pytest -q test/test_image_task_service.py::ImageTaskServiceTests::test_submit_generation_returns_prompt_and_client_task_metadata
```

Expected: pass.

- [ ] **Step 5: Run task service tests**

Run:

```bash
uv run pytest -q test/test_image_task_service.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add services/image_task_service.py test/test_image_task_service.py
git commit -m "Expose image task prompt metadata"
```

---

### Task 2: Add Strict Gateway Requirement for External Model Mode

**Files:**
- Modify: `services/config.py`
- Modify: `services/model_gateway_service.py`
- Modify: `services/image_task_service.py`
- Modify: `.env.example`
- Test: `test/test_config.py`
- Test: `test/test_image_task_service.py`

- [ ] **Step 1: Write config tests**

Add to `test/test_config.py`:

```python
def test_require_model_gateway_uses_env_or_config(self) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "config.json"
        config_path.write_text(
            json.dumps({"auth-key": "test-auth", "require_model_gateway": True}),
            encoding="utf-8",
        )

        module = self.config_module
        old_env = module.os.environ.get("HAPPYIMAGE_REQUIRE_MODEL_GATEWAY")
        try:
            module.os.environ.pop("HAPPYIMAGE_REQUIRE_MODEL_GATEWAY", None)
            store = module.ConfigStore(config_path)
            self.assertTrue(store.require_model_gateway)

            module.os.environ["HAPPYIMAGE_REQUIRE_MODEL_GATEWAY"] = "false"
            self.assertFalse(store.require_model_gateway)
        finally:
            if old_env is None:
                module.os.environ.pop("HAPPYIMAGE_REQUIRE_MODEL_GATEWAY", None)
            else:
                module.os.environ["HAPPYIMAGE_REQUIRE_MODEL_GATEWAY"] = old_env
```

- [ ] **Step 2: Write task service missing-gateway test**

Add to `test/test_image_task_service.py`:

```python
def test_required_gateway_missing_marks_task_error_without_local_fallback(self):
    identity = {"id": "user-1", "role": "user", "image_quota": 10}
    local_handler_called = False

    def local_handler(_payload):
        nonlocal local_handler_called
        local_handler_called = True
        return {"data": [{"url": "http://local.test/image.png"}]}

    service = self.make_service(generation_handler=local_handler)

    with patch("services.model_gateway_service.is_required", return_value=True), \
         patch("services.model_gateway_service.is_enabled", return_value=False):
        task = service.submit_generation(
            identity,
            client_task_id="missing-gateway",
            prompt="a clean product photo",
            model="gpt-image-2",
            size=None,
            quality="auto",
        )
        service.wait_for_task("user-1", "missing-gateway", timeout=3)

    saved = service.list_tasks(identity, ["missing-gateway"])[0]
    assert task["status"] == "queued"
    assert saved["status"] == "error"
    assert "model gateway is not configured" in saved["error"]
    assert local_handler_called is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest -q test/test_config.py::ConfigLoadingTests::test_require_model_gateway_uses_env_or_config
uv run pytest -q test/test_image_task_service.py::ImageTaskServiceTests::test_required_gateway_missing_marks_task_error_without_local_fallback
```

Expected: first fails because `require_model_gateway` does not exist; second fails because strict gateway behavior is not implemented.

- [ ] **Step 4: Implement config property**

In `services/config.py`, add this property near `model_gateway_api_key`:

```python
@property
def require_model_gateway(self) -> bool:
    value = (
        _getenv("HAPPYIMAGE_REQUIRE_MODEL_GATEWAY")
        or self.data.get("require_model_gateway")
        or False
    )
    return _normalize_bool(value, False)
```

In `get()`, include the redacted boolean:

```python
data["require_model_gateway"] = self.require_model_gateway
```

- [ ] **Step 5: Implement gateway helper and strict error**

In `services/model_gateway_service.py`, add:

```python
class ModelGatewayConfigurationError(RuntimeError):
    pass


def is_required() -> bool:
    return bool(config.require_model_gateway)


def ensure_available() -> None:
    if is_required() and not is_enabled():
        raise ModelGatewayConfigurationError("model gateway is not configured")
```

- [ ] **Step 6: Use strict gateway behavior in image tasks**

In `services/image_task_service.py`, update the gateway branch inside `_run_task`:

```python
from services import model_gateway_service

model_gateway_service.ensure_available()
if model_gateway_service.is_enabled():
    result = (
        model_gateway_service.edit_image(payload_with_progress)
        if mode == "edit"
        else model_gateway_service.generate_image(payload_with_progress)
    )
else:
    handler = self.edit_handler if mode == "edit" else self.generation_handler
    result = handler(payload_with_progress)
```

This preserves legacy local fallback unless `HAPPYIMAGE_REQUIRE_MODEL_GATEWAY=true` or `require_model_gateway` is enabled in config.

- [ ] **Step 7: Document the flag**

In `.env.example`, add:

```bash
# When true, /api/image-tasks/* fails clearly if HAPPYIMAGE_MODEL_GATEWAY_* is missing.
# HAPPYIMAGE_REQUIRE_MODEL_GATEWAY=true
```

- [ ] **Step 8: Run focused tests**

Run:

```bash
uv run pytest -q test/test_config.py::ConfigLoadingTests::test_require_model_gateway_uses_env_or_config
uv run pytest -q test/test_image_task_service.py::ImageTaskServiceTests::test_required_gateway_missing_marks_task_error_without_local_fallback
```

Expected: both pass.

- [ ] **Step 9: Run broader API tests**

Run:

```bash
uv run pytest -q test/test_config.py test/test_image_task_service.py test/test_image_tasks_api.py
```

Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add .env.example services/config.py services/model_gateway_service.py services/image_task_service.py test/test_config.py test/test_image_task_service.py
git commit -m "Require configured model gateway in external mode"
```

---

### Task 3: Harden Gateway Failure and Idempotency Tests

**Files:**
- Modify: `test/test_image_task_service.py`
- Modify: `test/test_image_tasks_api.py`
- Modify: `services/image_task_service.py`

- [ ] **Step 1: Add idempotency test at service level**

Add to `test/test_image_task_service.py`:

```python
def test_duplicate_client_task_id_returns_existing_task_without_second_gateway_call(self):
    identity = {"id": "user-1", "role": "user", "image_quota": 10}
    calls = 0

    def handler(_payload):
        nonlocal calls
        calls += 1
        return {"data": [{"url": "http://example.test/image.png"}]}

    service = self.make_service(generation_handler=handler)

    first = service.submit_generation(
        identity,
        client_task_id="dupe-001",
        prompt="first prompt",
        model="gpt-image-2",
        size=None,
        quality="auto",
    )
    second = service.submit_generation(
        identity,
        client_task_id="dupe-001",
        prompt="second prompt",
        model="gpt-image-2",
        size=None,
        quality="auto",
    )
    service.wait_for_task("user-1", "dupe-001", timeout=3)

    assert first["id"] == second["id"] == "dupe-001"
    assert second["prompt"] == "first prompt"
    assert calls == 1
```

- [ ] **Step 2: Add gateway failure persistence test**

Add to `test/test_image_task_service.py`:

```python
def test_gateway_failure_is_persisted_as_restorable_error_task(self):
    identity = {"id": "user-1", "role": "user", "image_quota": 10}

    def handler(_payload):
        raise RuntimeError("gateway quota exhausted")

    service = self.make_service(generation_handler=handler)
    service.submit_generation(
        identity,
        client_task_id="gateway-error-001",
        prompt="a clean product photo",
        model="gpt-image-2",
        size=None,
        quality="auto",
    )
    service.wait_for_task("user-1", "gateway-error-001", timeout=3)

    task = service.list_tasks(identity, ["gateway-error-001"])[0]
    assert task["status"] == "error"
    assert task["prompt"] == "a clean product photo"
    assert "gateway quota exhausted" in task["error"]
```

- [ ] **Step 3: Add HTTP API idempotency test**

Add to `test/test_image_tasks_api.py`:

```python
def test_generation_duplicate_client_task_id_returns_existing_task(self):
    payload = {
        "client_task_id": "api-dupe-001",
        "prompt": "a clean product photo",
        "model": "gpt-image-2",
        "quality": "auto",
    }

    first = self.client.post("/api/image-tasks/generations", json=payload, headers=AUTH_HEADERS)
    second = self.client.post(
        "/api/image-tasks/generations",
        json={**payload, "prompt": "different prompt"},
        headers=AUTH_HEADERS,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"] == "api-dupe-001"
    assert second.json()["prompt"] == "a clean product photo"
```

- [ ] **Step 4: Run tests to verify behavior**

Run:

```bash
uv run pytest -q \
  test/test_image_task_service.py::ImageTaskServiceTests::test_duplicate_client_task_id_returns_existing_task_without_second_gateway_call \
  test/test_image_task_service.py::ImageTaskServiceTests::test_gateway_failure_is_persisted_as_restorable_error_task \
  test/test_image_tasks_api.py::ImageTasksApiTests::test_generation_duplicate_client_task_id_returns_existing_task
```

Expected: pass if current behavior already satisfies the PRD; otherwise fail with a concrete contract gap.

- [ ] **Step 5: Confirm or add the exact idempotency and failure-state implementation**

In `_submit`, make the stored-task branch exactly match this behavior before any new task is created:

```python
task = self._tasks.get(key)
if task is not None:
    if cleaned:
        self._save_locked()
    return _public_task(task)
```

In `_run_task`, make the exception path persist the task as an error with this behavior:

```python
except Exception as exc:
    error_message = str(exc) or exc.__class__.__name__
    duration_ms = int((time.time() - started) * 1000)
    self._update_task(key, status=TASK_STATUS_ERROR, error=error_message, data=[], duration_ms=duration_ms)
```

- [ ] **Step 6: Run task tests**

Run:

```bash
uv run pytest -q test/test_image_task_service.py test/test_image_tasks_api.py
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add services/image_task_service.py test/test_image_task_service.py test/test_image_tasks_api.py
git commit -m "Harden image task idempotency and failure tests"
```

---

### Task 4: Add Web Middleware Routing Tests

**Files:**
- Create: `src/middleware.test.ts` in `/Users/forever/workspace/happyimage-web`
- Modify: `src/middleware.ts`
- Modify: `package.json`
- Modify: `pnpm-lock.yaml`

- [ ] **Step 1: Install Vitest**

Run in `/Users/forever/workspace/happyimage-web`:

```bash
pnpm add -D vitest
```

Expected: `vitest` is added to `devDependencies` and `pnpm-lock.yaml` is updated.

- [ ] **Step 2: Extract middleware routing helper**

In `src/middleware.ts`, extract routing into exported pure helpers:

```ts
export function isModelPath(pathname: string) {
  return pathname === "/v1" || pathname.startsWith("/v1/");
}

export function getProxyTargetBase(pathname: string) {
  return isModelPath(pathname) ? MODEL_BACKEND_BASE : BACKEND_BASE;
}

export function buildProxyHeaders(pathname: string, incoming: Headers) {
  const headers = new Headers(incoming);
  if (isModelPath(pathname) && MODEL_BACKEND_API_KEY) {
    headers.set("authorization", `Bearer ${MODEL_BACKEND_API_KEY}`);
  }
  return headers;
}
```

Update the middleware implementation to call these helpers instead of duplicating path checks:

```ts
const targetBase = getProxyTargetBase(pathname);
const headers = buildProxyHeaders(pathname, request.headers);
```

- [ ] **Step 3: Add tests for routing and auth replacement**

Create `src/middleware.test.ts`:

```ts
import assert from "node:assert/strict";
import test from "node:test";

import { buildProxyHeaders, getProxyTargetBase, isModelPath } from "./middleware";

test("isModelPath only matches /v1 and /v1/*", () => {
  assert.equal(isModelPath("/v1"), true);
  assert.equal(isModelPath("/v1/models"), true);
  assert.equal(isModelPath("/api/image-tasks"), false);
  assert.equal(isModelPath("/images/a.png"), false);
});

test("getProxyTargetBase routes product and model paths separately", () => {
  assert.equal(getProxyTargetBase("/api/image-tasks"), process.env.BACKEND_URL || "http://127.0.0.1:8000");
  assert.equal(getProxyTargetBase("/v1/models"), process.env.MODEL_BACKEND_URL || process.env.NEXT_PUBLIC_MODEL_API_BASE_URL || process.env.BACKEND_URL || "http://127.0.0.1:8000");
});

test("buildProxyHeaders replaces authorization only for model paths when server token is configured", () => {
  const productHeaders = buildProxyHeaders("/api/image-tasks", new Headers({ authorization: "Bearer user-token" }));
  assert.equal(productHeaders.get("authorization"), "Bearer user-token");

  const modelHeaders = buildProxyHeaders("/v1/models", new Headers({ authorization: "Bearer browser-token" }));
  if (process.env.MODEL_BACKEND_API_KEY) {
    assert.equal(modelHeaders.get("authorization"), `Bearer ${process.env.MODEL_BACKEND_API_KEY}`);
  } else {
    assert.equal(modelHeaders.get("authorization"), "Bearer browser-token");
  }
});
```

- [ ] **Step 4: Add unit test script**

In `package.json`, add `test:unit` to `scripts`:

```json
{
  "scripts": {
    "test:unit": "vitest run"
  }
}
```

- [ ] **Step 5: Run tests and typecheck**

Run:

```bash
MODEL_BACKEND_API_KEY=sk-test MODEL_BACKEND_URL=http://127.0.0.1:3001 BACKEND_URL=http://127.0.0.1:8000 pnpm test:unit
pnpm exec tsc --noEmit
```

Expected: middleware tests pass and TypeScript has no errors.

- [ ] **Step 6: Commit**

```bash
git add src/middleware.ts src/middleware.test.ts package.json pnpm-lock.yaml
git commit -m "Test web model proxy middleware"
```

---

### Task 5: Add End-to-End Acceptance Script and Documentation

**Files:**
- Create: `scripts/verify-newapi-model-chain.sh`
- Modify: `README.md`
- Test: local running `happyimage-api`, `happyimage-web`, `new-api`

- [ ] **Step 1: Create verification script**

Create `scripts/verify-newapi-model-chain.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

WEB_URL="${WEB_URL:-http://127.0.0.1:3000}"
API_URL="${API_URL:-http://127.0.0.1:8000}"
HAPPYIMAGE_AUTH_KEY="${HAPPYIMAGE_AUTH_KEY:-}"

if [[ -z "$HAPPYIMAGE_AUTH_KEY" ]]; then
  if [[ -f config.json ]]; then
    HAPPYIMAGE_AUTH_KEY="$(jq -r '."auth-key" // empty' config.json)"
  fi
fi

if [[ -z "$HAPPYIMAGE_AUTH_KEY" ]]; then
  echo "HAPPYIMAGE_AUTH_KEY is required or config.json must contain auth-key" >&2
  exit 1
fi

echo "Checking web /v1/models via NewAPI middleware..."
models="$(curl -fsS "$WEB_URL/v1/models" -H "Authorization: Bearer browser-token")"
echo "$models" | jq -e '.object == "list" and (.data | length > 0)' >/dev/null

echo "Checking API settings redacts model gateway key..."
settings="$(curl -fsS "$API_URL/api/settings" -H "Authorization: Bearer $HAPPYIMAGE_AUTH_KEY")"
echo "$settings" | jq -e '.config | has("model_gateway_api_key") | not' >/dev/null

echo "Checking task API creates a restorable task..."
task_id="verify-$(date +%s)"
task="$(curl -fsS "$API_URL/api/image-tasks/generations" \
  -H "Authorization: Bearer $HAPPYIMAGE_AUTH_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"client_task_id\":\"$task_id\",\"prompt\":\"a clean product photo\",\"model\":\"gpt-image-2\",\"quality\":\"auto\"}")"
echo "$task" | jq -e --arg id "$task_id" '.id == $id and (.status == "queued" or .status == "running" or .status == "success" or .status == "error")' >/dev/null

restored="$(curl -fsS "$API_URL/api/image-tasks?ids=$task_id" -H "Authorization: Bearer $HAPPYIMAGE_AUTH_KEY")"
echo "$restored" | jq -e --arg id "$task_id" '.items[0].id == $id or .[0].id == $id' >/dev/null

echo "NewAPI model chain verification passed."
```

- [ ] **Step 2: Make it executable**

Run:

```bash
chmod +x scripts/verify-newapi-model-chain.sh
```

- [ ] **Step 3: Document usage**

Add to `README.md` under the NewAPI gateway section:

```markdown
### End-to-end verification

With `happyimage-api`, `happyimage-web`, and NewAPI running:

```bash
WEB_URL=http://127.0.0.1:3000 \
API_URL=http://127.0.0.1:8000 \
./scripts/verify-newapi-model-chain.sh
```

The script checks:

- web `/v1/models` reaches the model gateway path
- `/api/settings` redacts the model gateway token
- `/api/image-tasks/generations` creates a restorable HappyImage task
```
```

- [ ] **Step 4: Run script**

Run:

```bash
WEB_URL=http://127.0.0.1:3000 API_URL=http://127.0.0.1:8000 ./scripts/verify-newapi-model-chain.sh
```

Expected: `NewAPI model chain verification passed.` If upstream NewAPI quota is exhausted, the task may end in `error`, but it must still be restorable.

- [ ] **Step 5: Run full backend tests**

Run:

```bash
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add README.md scripts/verify-newapi-model-chain.sh
git commit -m "Add NewAPI model chain verification script"
```

---

## Final Verification

- [ ] Run backend full test suite:

```bash
uv run pytest -q
```

Expected: all tests pass.

- [ ] Run web typecheck and middleware unit tests:

```bash
cd /Users/forever/workspace/happyimage-web
pnpm exec tsc --noEmit
MODEL_BACKEND_API_KEY=sk-test MODEL_BACKEND_URL=http://127.0.0.1:3001 BACKEND_URL=http://127.0.0.1:8000 pnpm test:unit
```

Expected: typecheck and tests pass.

- [ ] Run local chain verification:

```bash
cd /Users/forever/workspace/happyimage-api
WEB_URL=http://127.0.0.1:3000 API_URL=http://127.0.0.1:8000 ./scripts/verify-newapi-model-chain.sh
```

Expected: script prints `NewAPI model chain verification passed.`

- [ ] Confirm external admin mode manually:

```bash
curl -fsS http://127.0.0.1:3000/v1/models -H "Authorization: Bearer browser-token" | jq '.object'
```

Expected: `"list"`.

---

## Self-Review Notes

- Spec coverage: The plan covers task proxy behavior, model gateway configuration, history/gallery task persistence, idempotency, web `/v1/*` routing, token redaction, external admin mode, and manual acceptance.
- Explicitly deferred: NewAPI callback/webhook sync, direct browser-to-NewAPI image workflow, and `/v1/chat/completions` or `/v1/responses` user-visible history.
- No vague steps remain; every task has concrete tests, implementation snippets, commands, and expected results.
