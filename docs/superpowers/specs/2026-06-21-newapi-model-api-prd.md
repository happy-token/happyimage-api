# NewAPI Model API PRD

## 1. Background

HappyImage is moving model account management, upstream debugging, and GPT reverse-engineering concerns out of the HappyImage product surface and into NewAPI. HappyImage should remain the user workspace: login/session, image history, gallery, task state, storage, user quota, and system configuration.

The first PRD goal is to define the model API boundary clearly enough that future implementation work can be split without drifting back into local account-pool management.

## 2. Goals

1. Define the model API list for future clients and internal calls.
2. Keep the project design centered on a lightweight task proxy:
   `happyimage-web -> happyimage-api /api/image-tasks/* -> NewAPI /v1/images/* -> happyimage-api history/gallery`.
3. Preserve HappyImage product data: user sessions, history, gallery, image task state, feedback, storage configuration, and model gateway configuration.
4. Treat NewAPI as the external place for account pools, model debugging, upstream account configuration, channels, and model token routing.
5. Provide enough request, response, auth, idempotency, and test detail for engineering and QA planning.

## 3. Non-Goals

1. Do not keep local account-pool management as a primary HappyImage workflow.
2. Do not expose NewAPI tokens to the browser.
3. Do not make `/v1/chat/completions` or `/v1/responses` part of the happyimage-web main image workflow in the first phase.
4. Do not route HappyImage product APIs through NewAPI.
5. Do not require NewAPI callback/webhook support for the first phase.

## 4. System Roles

| System | Responsibility |
|:--|:--|
| `happyimage-web` | Product UI, login-aware workspace, image creation screen, gallery, history, settings. |
| `happyimage-api` | Product backend, session/auth, image task persistence, gallery/storage, lightweight model proxy, OpenAI-compatible upstream surface. |
| `NewAPI` | External model gateway, token/channel/account-pool management, model debugging, upstream routing, quota/billing rules outside HappyImage. |

## 5. Architecture Decision

The first-phase sync strategy is **B: lightweight task proxy**.

```text
happyimage-web
  -> happyimage-api /api/image-tasks/*
  -> happyimage-api records identity, session, task, status, history, gallery intent
  -> NewAPI /v1/images/*
  -> happyimage-api stores result/error and image references
  -> happyimage-web polls or restores history/gallery from happyimage-api
```

This keeps historical data reliable while still externalizing upstream model account management to NewAPI.

Direct `happyimage-web -> NewAPI /v1/images/*` and NewAPI webhook sync can be considered later, but they are not first-phase requirements because they increase risk around lost history, browser interruption, token exposure, and user identity mapping.

## 6. API Scope

### 6.1 Included: OpenAI-Compatible Core Model APIs

These are model protocol interfaces. They may be called by NewAPI, external OpenAI-compatible clients, or happyimage-web middleware in limited compatibility scenarios.

| Method | Path | First-phase role |
|:--|:--|:--|
| `GET` | `/v1/models` | Model discovery and NewAPI model sync. |
| `POST` | `/v1/images/generations` | OpenAI-compatible text-to-image generation. |
| `POST` | `/v1/images/edits` | OpenAI-compatible image edit/image-to-image generation. |
| `POST` | `/v1/chat/completions` | Compatibility entry, retained but not the main web image workflow. |
| `POST` | `/v1/responses` | Compatibility entry, retained but not the main web image workflow. |

### 6.2 Included: HappyImage Product Task APIs

These are product-state APIs. They are the main happyimage-web image workflow in the first phase.

| Method | Path | First-phase role |
|:--|:--|:--|
| `GET` | `/api/image-tasks` | Restore current user task history by IDs or list. |
| `POST` | `/api/image-tasks/generations` | Create text-to-image task, record history, call model gateway. |
| `POST` | `/api/image-tasks/edits` | Create image-edit task, persist uploads/result, call model gateway. |
| `POST` | `/api/image-tasks/{task_id}/resume-poll` | Continue waiting after timeout without losing task state. |
| `POST` | `/api/image-tasks/{task_id}/feedback` | Record image-level user feedback. |

### 6.3 Explicitly Excluded from Model API Flow

These remain admin/product APIs or are hidden when external NewAPI management is enabled.

| Path group | Decision |
|:--|:--|
| `/api/accounts/*` | Not part of model API PRD; local account pool management is externalized to NewAPI. |
| `/api/cpa/*` | Not part of first-phase HappyImage model workflow. |
| `/api/sub2api/*` | Not part of first-phase HappyImage model workflow. |
| Debug pages and upstream account settings | Managed in NewAPI, hidden from HappyImage Web when `NEXT_PUBLIC_EXTERNAL_MODEL_ADMIN=true`. |

## 7. Interface Requirements

### 7.1 `GET /v1/models`

| Item | Requirement |
|:--|:--|
| Purpose | Return OpenAI-compatible model list for NewAPI sync and external clients. |
| Caller | NewAPI, external clients, optional web middleware compatibility path. |
| Auth | `Authorization: Bearer <HappyImage user key or admin key>`. |
| Request | No body. |
| Response | OpenAI-compatible list object: `{"object":"list","data":[{"id":"gpt-image-2",...}]}`. |
| History/gallery write | No. |
| NewAPI path | NewAPI may call this when HappyImage is configured as upstream. |
| Errors | `401` invalid auth, `502` upstream/model-list failure. |
| Tests | Verify auth required; response contains `object=list`; response includes supported image model IDs. |

### 7.2 `POST /v1/images/generations`

| Item | Requirement |
|:--|:--|
| Purpose | OpenAI-compatible text-to-image generation endpoint. |
| Caller | NewAPI upstream call, external clients. Not the preferred happyimage-web first-phase entry. |
| Auth | `Authorization: Bearer <HappyImage user key or admin key>`. |
| Request fields | `prompt` required; `model` default `gpt-image-2`; `n` 1-4; `size` optional; `quality` default `auto`; `response_format` default `b64_json`; `stream` accepted for compatibility. |
| Response | OpenAI-compatible image response with `data` array containing URL or base64 data depending on response format. |
| History/gallery write | Yes when owner identity is resolved by HappyImage image handling; direct external behavior must not be relied on for product history. |
| NewAPI path | Used when NewAPI points to HappyImage as an OpenAI-compatible upstream. |
| Errors | `400` invalid payload, `401` invalid auth, `429` insufficient image quota, `502/5xx` upstream generation failure. |
| Tests | Validate payload schema, quota reservation/refund on failure, response shape, and NewAPI upstream compatibility. |

### 7.3 `POST /v1/images/edits`

| Item | Requirement |
|:--|:--|
| Purpose | OpenAI-compatible image edit/image-to-image endpoint. |
| Caller | NewAPI upstream call, external clients. Not the preferred happyimage-web first-phase entry. |
| Auth | `Authorization: Bearer <HappyImage user key or admin key>`. |
| Request fields | Multipart `image` required or JSON/data URL compatibility; `prompt` required; `model` default `gpt-image-2`; `n` 1-4; `size` optional; `quality` default `auto`; `response_format` accepted. |
| Response | OpenAI-compatible image response with `data` array. |
| History/gallery write | Same as generations: possible through backend owner handling, but happyimage-web should use `/api/image-tasks/edits` for reliable product history. |
| NewAPI path | Used when NewAPI points to HappyImage as upstream. |
| Errors | `400` missing image/prompt, `401`, `413` oversized upload if enforced, `429`, `502/5xx`. |
| Tests | Multipart upload, JSON image source compatibility, auth, error response, response shape. |

### 7.4 `POST /v1/chat/completions`

| Item | Requirement |
|:--|:--|
| Purpose | Retained OpenAI-compatible chat entry. |
| Caller | External clients or NewAPI compatibility. |
| Auth | `Authorization: Bearer <HappyImage user key or admin key>`. |
| Request fields | OpenAI-compatible fields including `model`, `messages`, `prompt`, `stream`, extra fields allowed. |
| Response | OpenAI-compatible chat completion or stream. |
| History/gallery write | No image gallery write in first phase. |
| First-phase status | Compatible but not a happyimage-web main workflow. |
| Errors | `400`, `401`, model/upstream errors. |
| Tests | Compatibility smoke test, auth, content filter failure path if applicable. |

### 7.5 `POST /v1/responses`

| Item | Requirement |
|:--|:--|
| Purpose | Retained OpenAI-compatible Responses entry, including future tool compatibility. |
| Caller | External clients or NewAPI compatibility. |
| Auth | `Authorization: Bearer <HappyImage user key or admin key>`. |
| Request fields | `model`, `input`, `tools`, `tool_choice`, `stream`, extra compatible fields. |
| Response | OpenAI-compatible Responses object or stream. |
| History/gallery write | No image gallery write in first phase unless later explicitly designed for image generation tool outputs. |
| First-phase status | Compatible but not a happyimage-web main workflow. |
| Errors | `400`, `401`, model/upstream errors. |
| Tests | Compatibility smoke test, auth, response shape. |

### 7.6 `GET /api/image-tasks`

| Item | Requirement |
|:--|:--|
| Purpose | Restore user-visible task history and active task state. |
| Caller | happyimage-web. |
| Auth | Cookie session or Bearer key resolved by HappyImage. |
| Request fields | Optional `ids` comma-separated task IDs. |
| Response | List of tasks owned by the current identity, including status, prompt, model, created time, result URLs, errors, and feedback where available. |
| History/gallery write | No new write; read path only. |
| NewAPI path | Does not go through NewAPI. |
| Errors | `401` unauthenticated; `403/404` if task ownership checks are introduced for direct ID access. |
| Tests | User can restore own tasks after login; user cannot read another user's tasks; DB/json storage compatibility. |

### 7.7 `POST /api/image-tasks/generations`

| Item | Requirement |
|:--|:--|
| Purpose | First-phase happyimage-web text-to-image entry. Creates product task, calls NewAPI through server-side model gateway, stores result. |
| Caller | happyimage-web. |
| Auth | Cookie session or Bearer key resolved by HappyImage. |
| Request fields | `client_task_id` required for idempotency; `prompt` required; `model` optional default `gpt-image-2`; `size` optional; `quality` default `auto`. |
| Response | Task object is returned immediately with `status=queued` or the existing terminal/in-flight task for the same `client_task_id`. The object must include `id`, `status`, prompt/model metadata, and eventual result/error fields on later reads. |
| History/gallery write | Yes. This is the reliable history/gallery entry. |
| NewAPI path | Calls `HAPPYIMAGE_MODEL_GATEWAY_BASE_URL + /images/generations` with server-side `HAPPYIMAGE_MODEL_GATEWAY_API_KEY` when configured. |
| Idempotency | Duplicate `client_task_id` for same owner should return existing task or avoid duplicate generation. |
| Errors | `400` invalid prompt/client_task_id; `401`; `429` quota/gateway quota; `502` model gateway failure; timeout status should preserve task. |
| Tests | Happy path through mocked gateway; duplicate `client_task_id`; gateway failure creates failed task; login user can restore task. |

### 7.8 `POST /api/image-tasks/edits`

| Item | Requirement |
|:--|:--|
| Purpose | First-phase happyimage-web image-edit entry. Persists task and uploaded image context, calls NewAPI through server-side model gateway, stores result. |
| Caller | happyimage-web. |
| Auth | Cookie session or Bearer key resolved by HappyImage. |
| Request fields | Multipart `client_task_id`, `prompt`, one or more `image` files, optional `model`, `size`, `quality`. |
| Response | Task object with status/result/error fields. |
| History/gallery write | Yes. |
| NewAPI path | Calls `HAPPYIMAGE_MODEL_GATEWAY_BASE_URL + /images/edits` with server-side token and multipart files. |
| Idempotency | Same as generation. Upload handling must not duplicate history on retry. |
| Errors | `400` missing prompt/image/client_task_id; `401`; `413` oversized upload if enforced; `429`; `502`; timeout preserves task. |
| Tests | Multipart task creation; gateway multipart forwarding; duplicate task handling; failed gateway response stored and restorable. |

### 7.9 `POST /api/image-tasks/{task_id}/resume-poll`

| Item | Requirement |
|:--|:--|
| Purpose | Continue waiting for a timed-out or pending task without creating a new generation. |
| Caller | happyimage-web. |
| Auth | Cookie session or Bearer key resolved by HappyImage. |
| Request fields | Optional `extra_timeout_secs`, default from settings. |
| Response | Updated task object. |
| History/gallery write | Updates task status/result if available. |
| NewAPI path | Extends or resumes waiting for the existing task state only. It must not create a second NewAPI generation/edit job for the same task. |
| Errors | `401`, `404`, `409` if task is not resumable, `502` gateway/result fetch failure. |
| Tests | Resuming pending task; refusing completed/foreign task; preserving original `client_task_id`. |

### 7.10 `POST /api/image-tasks/{task_id}/feedback`

| Item | Requirement |
|:--|:--|
| Purpose | Record user feedback for generated images. |
| Caller | happyimage-web. |
| Auth | Cookie session or Bearer key resolved by HappyImage. |
| Request fields | `image_index`, `vote`; `vote` is `like`, `dislike`, or `null` to clear existing feedback. |
| Response | Updated task object or feedback state. |
| History/gallery write | Yes, feedback metadata only. |
| NewAPI path | Does not go through NewAPI. |
| Errors | `400` invalid index/vote; `401`; `404`; `403` foreign task. |
| Tests | Add/update/remove feedback; ownership enforcement; persistence across reload. |

## 8. Configuration Requirements

| Variable / Setting | Purpose | Security |
|:--|:--|:--|
| `HAPPYIMAGE_MODEL_GATEWAY_BASE_URL` | Server-side OpenAI-compatible model gateway base, usually NewAPI `/v1`. | Not secret. |
| `HAPPYIMAGE_MODEL_GATEWAY_API_KEY` | Server-side model gateway token. | Secret; never returned raw to web. |
| `MODEL_BACKEND_URL` | happyimage-web middleware target for `/v1/*` compatibility requests. | Server-side web env. |
| `MODEL_BACKEND_API_KEY` | happyimage-web middleware token used when proxying `/v1/*`. | Secret; not exposed to browser. |
| `NEXT_PUBLIC_EXTERNAL_MODEL_ADMIN` | Hide local account/debug/admin upstream management in web. | Public boolean. |
| `STORAGE_BACKEND` / `DATABASE_URL` | Persist users, task history, and gallery data. | Database URL secret. |

Runtime rule: deployment environment variables take priority over web-saved settings. If the admin UI sends an empty model gateway token, the existing token must be preserved.

## 9. Data and Identity Rules

1. HappyImage identity owns product data. All `/api/image-tasks/*` records must bind to the logged-in user or admin identity.
2. NewAPI token identity is not the product identity. It authenticates the server-to-gateway call only.
3. `client_task_id` is the idempotency key for browser retries and refresh-safe task restoration.
4. Successful generation must store enough data for gallery restoration: prompt, model, mode, timestamps, result image refs, owner, status, and storage refs.
5. Failed or timed-out generation must still create/update a task record so the UI can show the failure and allow retry/resume when applicable.
6. Product APIs must continue to support database-backed storage so users can recover history after login.

## 10. Error Handling

| Case | Expected behavior |
|:--|:--|
| Missing/invalid HappyImage auth | Return `401`; do not call NewAPI. |
| Missing gateway configuration | In external model-admin deployments, return a clear model gateway configuration error for task APIs. Legacy/local deployments may keep an explicit local fallback, but that fallback is outside the NewAPI-first PRD path. |
| NewAPI rejects token/quota | Store failed task with gateway error; return task/error to UI; do not lose history. |
| NewAPI timeout | Mark task pending/timeout based on current task semantics; allow resume if feasible. |
| Browser retry | Use `client_task_id` to avoid duplicate model calls. |
| Image storage failure after model success | Preserve task result metadata and expose storage error; avoid charging/generating again on retry. |

## 11. Test Matrix

### 11.1 Backend Unit and Integration Tests

| Area | Required tests |
|:--|:--|
| Config | Gateway base URL/key load from env and config; raw key redaction; blank UI token preserves existing token. |
| Task generation | `/api/image-tasks/generations` records task, calls gateway, stores success/failure. |
| Task edit | Multipart upload is forwarded to gateway and persisted as a task. |
| Idempotency | Duplicate `client_task_id` does not create duplicate tasks or duplicate model calls. |
| Auth/ownership | Users can restore own tasks and cannot access others' tasks. |
| OpenAI compatibility | `/v1/models`, `/v1/images/generations`, `/v1/images/edits` return compatible shapes. |
| NewAPI chain | Simulated NewAPI token -> HappyImage upstream -> compatible response; `/api/*` remains outside NewAPI. |

Suggested commands:

```bash
uv run pytest -q test/test_config.py test/test_image_tasks_api.py test/test_image_task_service.py test/test_newapi_gateway_chain.py
uv run pytest -q
```

### 11.2 Web Tests

| Area | Required tests |
|:--|:--|
| Middleware routing | `/api/*` routes to `BACKEND_URL`; `/v1/*` routes to `MODEL_BACKEND_URL`; auth header is replaced server-side for `/v1/*`. |
| External admin mode | `NEXT_PUBLIC_EXTERNAL_MODEL_ADMIN=true` hides local account/debug/CPA/Sub2API surfaces. |
| Settings | Gateway URL and token can be edited; configured token placeholder is shown; raw token is never displayed. |
| Task UX | Refresh or login restore shows previous history/gallery records. |

Suggested command:

```bash
pnpm exec tsc --noEmit
```

### 11.3 Manual Chain Verification

```bash
# NewAPI-visible model list through web middleware
curl http://127.0.0.1:3000/v1/models \
  -H "Authorization: Bearer any-browser-token"

# HappyImage settings redacts model gateway token
curl http://127.0.0.1:8000/api/settings \
  -H "Authorization: Bearer <HappyImage admin key>"

# Task API remains the main web image workflow
curl http://127.0.0.1:8000/api/image-tasks/generations \
  -H "Authorization: Bearer <HappyImage user/admin key>" \
  -H "Content-Type: application/json" \
  -d '{"client_task_id":"prd-smoke-001","prompt":"a clean product photo","model":"gpt-image-2","quality":"auto"}'
```

Acceptance criteria:

1. `/v1/models` returns a NewAPI/OpenAI-compatible model list.
2. `/api/settings` reports `model_gateway_api_key_configured=true` when configured and never includes `model_gateway_api_key`.
3. `/api/image-tasks/generations` creates a restorable task record whether the gateway succeeds, fails, or times out.
4. The UI can reload after login and recover task history/gallery from HappyImage storage.
5. Local account-pool/debug surfaces are hidden when external admin mode is enabled.

## 12. Rollout Plan

1. Keep current lightweight task proxy as first-phase implementation.
2. Ensure all model gateway secrets are server-side only.
3. Add or harden idempotency around `client_task_id`.
4. Extend tests to cover gateway failure, timeout, and history restoration.
5. Document NewAPI setup and HappyImage setup in README.
6. Later evaluate direct NewAPI calls plus webhook/log sync only after NewAPI callback guarantees are clear.

## 13. Future Decisions Outside First Version

These items are not blockers for the first version of the PRD.

1. Whether failed tasks should count against HappyImage user quota when NewAPI already consumed upstream quota.
2. Final image result storage policy for remote NewAPI URLs: store URL only, WebDAV copy, local copy, or hybrid.
3. Whether `/v1/chat/completions` and `/v1/responses` should eventually write any user-visible history.
