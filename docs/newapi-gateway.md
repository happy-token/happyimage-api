# NewAPI Gateway

Happy Token can be used with NewAPI in two different directions. Keep these paths separate:

1. Register Happy Token API in NewAPI as an OpenAI-compatible upstream.
2. Let Happy Token Web keep product state in Happy Token API while sending model calls through NewAPI.

NewAPI is a model gateway, not the Happy Token application backend. Login, OIDC, history, user gallery, private image URLs, settings, and logs must keep using Happy Token `/api/*` routes.

For the visual architecture and data-flow diagrams, see [Architecture](architecture.md).

## Supported OpenAI-Compatible Surface

These endpoints can be exposed to NewAPI or other OpenAI-compatible clients:

| Endpoint | Purpose | Notes |
|:--|:--|:--|
| `GET /v1/models` | Model list | Returns image and text models supported by Happy Token. |
| `POST /v1/images/generations` | Text-to-image | Supports `prompt`, `model`, `n`, `size`, `quality`, `response_format`. |
| `POST /v1/images/edits` | Image edit | Supports multipart uploads and JSON data URLs. |
| `POST /v1/chat/completions` | Chat Completions compatibility | For text and multimodal workflows. |
| `POST /v1/responses` | Responses compatibility | Includes image-generation tool workflows. |

Use Bearer auth:

```http
Authorization: Bearer <Happy Token user token>
```

The following routes are not NewAPI OpenAI channel routes and should remain direct Happy Token application calls:

| Route family | Why it stays direct |
|:--|:--|
| `/api/auth/*`, `/api/settings`, `/api/accounts/*` | Login, OIDC, settings, and local user administration. |
| `/api/image-tasks/*` | Happy Token-owned task history, idempotency, and restore. |
| `/api/images/*`, `/images/*`, `/image-thumbnails/*` | Private signed image links, gallery storage, downloads, thumbnails. |
| `/api/seed-gallery/*`, `/api/share-drafts/*` | Product gallery and sharing features. |
| `POST /v1/messages`, `POST /v1/search`, `POST /v1/ppt/generations`, `POST /v1/psd/generations` | Happy Token extension routes, not standard OpenAI-compatible channel routes. |

## Direction A: Register Happy Token in NewAPI

In NewAPI, create an OpenAI-compatible or custom OpenAI API channel:

| Setting | Value |
|:--|:--|
| Base URL | `https://<happytoken-api-host>/v1` |
| API key | A Happy Token user token |
| Models | Sync from `GET /v1/models`; at minimum include `gpt-image-2` when using image generation. |

Verify through NewAPI:

```bash
curl https://<newapi-host>/v1/models \
  -H "Authorization: Bearer <NewAPI token>"

curl https://<newapi-host>/v1/images/generations \
  -H "Authorization: Bearer <NewAPI token>" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-image-2","prompt":"a small product photo on a white table","response_format":"b64_json"}'
```

## Direction B: Happy Token Web Uses NewAPI for Models

Use this mode when NewAPI owns upstream account pools, model debugging, and model-provider configuration, while Happy Token still owns the creation workspace.

Runtime split:

```text
Browser
  -> happytoken-web same-origin /api/*, /images/*, /image-thumbnails/*
      -> BACKEND_URL, usually happytoken-api

Browser
  -> happytoken-web same-origin /v1/*
      -> MODEL_BACKEND_URL, usually NewAPI /v1
      -> MODEL_BACKEND_API_KEY injected server-side

happytoken-api /api/image-tasks/*
  -> current user's selected provider Base URL, usually NewAPI /v1
  -> stores restorable task history and materialized image URLs
```

Local development example:

```bash
# happytoken-api
cd /path/to/happytoken-api
set -a; source .env; set +a
uv run python main.py

# happytoken-web
cd /path/to/happytoken-web
BACKEND_URL=http://127.0.0.1:8000 \
MODEL_BACKEND_URL=https://<newapi-host>/v1 \
MODEL_BACKEND_API_KEY=<newapi-token> \
NEXT_PUBLIC_EXTERNAL_MODEL_ADMIN=true \
pnpm dev
```

Do not set `NEXT_PUBLIC_API_BASE_URL` in same-origin proxy mode. If the page is opened at `http://localhost:3000` but `NEXT_PUBLIC_API_BASE_URL` is `http://127.0.0.1:3000`, the browser treats requests as cross-origin; history sync and private images can fail. Let browser API calls use relative URLs and let Next.js middleware proxy them.

## Happy Token API Provider Configuration

Happy Token API no longer uses `.env` model-gateway variables as a fallback for image generation. Normal users get a default HappyToken provider after Casdoor OIDC login. That provider is backed by a NewAPI user token created during binding, is selected by default, and cannot be deleted from the Web supplier list.

Users can add extra providers from the Web supplier picker:

| Provider | Configuration in Web |
|:--|:--|
| HappyToken | Auto-bound default provider; open `/settings/newapi` to view binding status and default API Key. |
| OpenAI | API Key only; Base URL and model presets are provided by the app. |
| Gemini / Nano Banana | API Key only; UI labels include `gemini-3.1-flash-image（Nano Banana 2）`, `gemini-3-pro-image（Nano Banana Pro）`, `gemini-2.5-flash-image（Nano Banana）`. |
| 火山方舟 / BytePlus ModelArk / 阿里云百炼 | API Key only; Base URL and presets are provided by the app. |
| Custom provider | Name, Base URL, model list and API Key. |

The protocol field is currently stored internally as OpenAI-compatible and is not shown in the Web form. The shared image-generation path still sends OpenAI Images API style requests, so providers that do not expose compatible image endpoints need a provider-specific adapter before they can work end to end.

If the current user has no selected provider with both Base URL and API Key, `/api/image-tasks/*` and `/v1/images/*` fail clearly instead of falling back to a server `.env` provider or the old local reverse-engineered account pool.

Successful gateway image outputs are materialized into Happy Token image storage. When NewAPI returns a remote `data[].url`, Happy Token API downloads it, saves it through `image_storage_service`, and returns a private `/images/...` URL. This keeps generated images restorable even if the upstream temporary image host is blocked or expires.

## HappyToken Management Page

`/settings/newapi` is the product management entry for the default HappyToken provider. It calls Happy Token API `/api/auth/newapi-management` with the current HappyImage session and displays the binding status, NewAPI user ID, default API Key and token list.

This page should not depend on an embedded NewAPI admin session. SQL/provisioning creates NewAPI database records and tokens, but it does not write a `gateway.happy-token.cn` browser `session` cookie. Because that cookie belongs to another origin and can be affected by frame and SameSite policies, direct NewAPI admin pages can show “not logged in” while HappyImage binding and model calls are already configured.

If users see `NewAPI SQL provisioning request failed`, check the returned binding status first:

- `configured`: the default HappyToken provider is ready; the message is stale UI state and should be cleared by the Web session refresh.
- `pending` or `failed`: login can still succeed, but the default HappyToken API Key may be missing or unusable until NewAPI SQL/provisioning is fixed.

## Verification

Unit and contract tests:

```bash
uv run pytest -q test/test_config.py test/test_image_task_service.py test/test_image_tasks_api.py test/test_newapi_gateway_chain.py
```

Live chain verification, with `happytoken-api` and `happytoken-web` already running:

```bash
WEB_URL=http://127.0.0.1:3000 \
API_URL=http://127.0.0.1:8000 \
HAPPYTOKEN_USER_TOKEN=<Happy Token user token> \
./scripts/verify-newapi-model-chain.sh
```

The script checks:

- Web `/v1/models` reaches the configured model gateway path.
- API image tasks use the current user's selected provider, not a server `.env` fallback.
- `/api/image-tasks/generations` creates a restorable Happy Token task.

## Production Notes

- Set stable `HAPPYTOKEN_SESSION_SECRET`; changing it logs out browser sessions and invalidates signed image links.
- Set `HAPPYTOKEN_BASE_URL`, `HAPPYTOKEN_API_BASE_URL`, and `HAPPYTOKEN_FRONTEND_BASE_URL` behind reverse proxies so OIDC callbacks and generated image URLs use public origins.
- Keep `.env`, `config.json`, and `data/*` outside git. They can contain user keys, upstream account tokens, session secrets, image data, and private logs.
- Use PostgreSQL or SQLite for persistent account and task storage when users must recover history after login.
