# NewAPI Gateway

HappyImage can be used with NewAPI in two different directions. Keep these paths separate:

1. Register HappyImage API in NewAPI as an OpenAI-compatible upstream.
2. Let HappyImage Web keep product state in HappyImage API while sending model calls through NewAPI.

NewAPI is a model gateway, not the HappyImage application backend. Login, OIDC, history, user gallery, private image URLs, recharge state, settings, and logs must keep using HappyImage `/api/*` routes.

For the visual architecture and data-flow diagrams, see [Architecture](architecture.md).

## Supported OpenAI-Compatible Surface

These endpoints can be exposed to NewAPI or other OpenAI-compatible clients:

| Endpoint | Purpose | Notes |
|:--|:--|:--|
| `GET /v1/models` | Model list | Returns image and text models supported by HappyImage. |
| `POST /v1/images/generations` | Text-to-image | Supports `prompt`, `model`, `n`, `size`, `quality`, `response_format`. |
| `POST /v1/images/edits` | Image edit | Supports multipart uploads and JSON data URLs. |
| `POST /v1/chat/completions` | Chat Completions compatibility | For text and multimodal workflows. |
| `POST /v1/responses` | Responses compatibility | Includes image-generation tool workflows. |

Use Bearer auth:

```http
Authorization: Bearer <HappyImage user key or HAPPYIMAGE_AUTH_KEY>
```

The following routes are not NewAPI OpenAI channel routes and should remain direct HappyImage application calls:

| Route family | Why it stays direct |
|:--|:--|
| `/api/auth/*`, `/api/settings`, `/api/accounts/*` | Login, OIDC, settings, and local user administration. |
| `/api/image-tasks/*` | HappyImage-owned task history, idempotency, quota accounting, and restore. |
| `/api/images/*`, `/images/*`, `/image-thumbnails/*` | Private signed image links, gallery storage, downloads, thumbnails. |
| `/api/seed-gallery/*`, `/api/share-drafts/*` | Product gallery and sharing features. |
| `/api/recharge/*` | Recharge session and NewAPI callback adapter. |
| `POST /v1/messages`, `POST /v1/search`, `POST /v1/ppt/generations`, `POST /v1/psd/generations` | HappyImage extension routes, not standard OpenAI-compatible channel routes. |

## Direction A: Register HappyImage in NewAPI

In NewAPI, create an OpenAI-compatible or custom OpenAI API channel:

| Setting | Value |
|:--|:--|
| Base URL | `https://<happyimage-api-host>/v1` |
| API key | A HappyImage user key or `HAPPYIMAGE_AUTH_KEY` |
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

## Direction B: HappyImage Web Uses NewAPI for Models

Use this mode when NewAPI owns upstream account pools, model debugging, and model-provider configuration, while HappyImage still owns the creation workspace.

Runtime split:

```text
Browser
  -> happyimage-web same-origin /api/*, /images/*, /image-thumbnails/*
      -> BACKEND_URL, usually happyimage-api

Browser
  -> happyimage-web same-origin /v1/*
      -> MODEL_BACKEND_URL, usually NewAPI /v1
      -> MODEL_BACKEND_API_KEY injected server-side

happyimage-api /api/image-tasks/*
  -> HAPPYIMAGE_MODEL_GATEWAY_BASE_URL, usually NewAPI /v1
  -> stores restorable task history and materialized image URLs
```

Local development example:

```bash
# happyimage-api
cd /path/to/happyimage-api
set -a; source .env; set +a
HAPPYIMAGE_REQUIRE_MODEL_GATEWAY=true uv run python main.py

# happyimage-web
cd /path/to/happyimage-web
set -a; source /path/to/happyimage-api/.env; set +a
BACKEND_URL=http://127.0.0.1:8000 \
MODEL_BACKEND_URL="$HAPPYIMAGE_MODEL_GATEWAY_BASE_URL" \
MODEL_BACKEND_API_KEY="$HAPPYIMAGE_MODEL_GATEWAY_API_KEY" \
NEXT_PUBLIC_EXTERNAL_MODEL_ADMIN=true \
pnpm dev
```

Do not set `NEXT_PUBLIC_API_BASE_URL` in same-origin proxy mode. If the page is opened at `http://localhost:3000` but `NEXT_PUBLIC_API_BASE_URL` is `http://127.0.0.1:3000`, the browser treats requests as cross-origin; history sync and private images can fail. Let browser API calls use relative URLs and let Next.js middleware proxy them.

## HappyImage API Gateway Configuration

Configure the model gateway in `.env` or deployment environment:

```bash
HAPPYIMAGE_MODEL_GATEWAY_BASE_URL=https://<newapi-host>/v1
HAPPYIMAGE_MODEL_GATEWAY_API_KEY=<newapi-token>
HAPPYIMAGE_REQUIRE_MODEL_GATEWAY=true
```

`HAPPYIMAGE_REQUIRE_MODEL_GATEWAY=true` makes `/api/image-tasks/*` fail clearly when gateway configuration is missing, instead of falling back to the local reverse-engineered account pool.

Successful gateway image outputs are materialized into HappyImage image storage. When NewAPI returns a remote `data[].url`, HappyImage API downloads it, saves it through `image_storage_service`, and returns a private `/images/...` URL. This keeps generated images restorable even if the upstream temporary image host is blocked or expires.

## Verification

Unit and contract tests:

```bash
uv run pytest -q test/test_config.py test/test_image_task_service.py test/test_image_tasks_api.py test/test_newapi_gateway_chain.py
```

Live chain verification, with `happyimage-api` and `happyimage-web` already running:

```bash
WEB_URL=http://127.0.0.1:3000 \
API_URL=http://127.0.0.1:8000 \
HAPPYIMAGE_AUTH_KEY=<same key configured for the running happyimage-api> \
./scripts/verify-newapi-model-chain.sh
```

The script checks:

- Web `/v1/models` reaches the configured model gateway path.
- API `/api/settings` redacts the model gateway token.
- `/api/image-tasks/generations` creates a restorable HappyImage task.

## Production Notes

- Set stable `HAPPYIMAGE_SESSION_SECRET`; changing it logs out browser sessions and invalidates signed image links.
- Set `HAPPYIMAGE_BASE_URL`, `HAPPYIMAGE_API_BASE_URL`, and `HAPPYIMAGE_FRONTEND_BASE_URL` behind reverse proxies so OIDC callbacks and generated image URLs use public origins.
- Keep `.env`, `config.json`, and `data/*` outside git. They can contain user keys, upstream account tokens, session secrets, image data, and private logs.
- Use PostgreSQL or SQLite for persistent account and task storage when users must recover history after login.
