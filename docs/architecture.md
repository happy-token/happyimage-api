# Architecture

This document is the visual entry point for the current Happy Token split architecture. It focuses on the recommended deployment where Happy Token Web owns the browser experience, Happy Token API owns product state, and NewAPI owns model gateway/account-pool operations.

## System Context

```mermaid
flowchart LR
  User["Browser User"]
  Web["happytoken-web<br/>Next.js UI + middleware"]
  API["happytoken-api<br/>FastAPI product backend"]
  NewAPI["NewAPI<br/>model gateway / account-pool admin"]
  Upstream["Upstream model providers<br/>OpenAI-compatible image/text models"]
  Store["Runtime storage<br/>JSON / SQLite / PostgreSQL / Git"]
  Images["Image storage<br/>local / WebDAV / both"]

  User -->|"same-origin UI"| Web
  Web -->|"/api/*, /images/*, /image-thumbnails/*"| API
  Web -->|"/v1/* model proxy"| NewAPI
  API -->|"selected user provider Base URL"| NewAPI
  NewAPI --> Upstream
  API --> Store
  API --> Images
```

Key boundary:

- `happytoken-web` is the browser-facing app and proxy layer.
- `happytoken-api` is the product-state owner for auth, sessions, image tasks, user gallery, private image links, logs, and settings.
- `NewAPI` is only the model gateway/account-pool management layer.

## Route Split

```mermaid
flowchart TD
  Browser["Browser at https://image.example.com"]
  Middleware["happytoken-web middleware"]
  ProductAPI["happytoken-api"]
  ModelGateway["NewAPI /v1"]

  Browser -->|"GET /image, /settings, /image-manager"| Middleware
  Browser -->|"GET/POST /api/*"| Middleware
  Browser -->|"GET /images/*"| Middleware
  Browser -->|"GET /image-thumbnails/*"| Middleware
  Browser -->|"GET/POST /v1/*"| Middleware

  Middleware -->|"BACKEND_URL"| ProductAPI
  Middleware -->|"MODEL_BACKEND_URL + MODEL_BACKEND_API_KEY"| ModelGateway

  ProductAPI -->|"auth, settings, image tasks, gallery"| ProductAPI
  ModelGateway -->|"models, images, chat, responses"| ModelGateway
```

Recommended browser configuration:

| Browser route | Web middleware target | Why |
|:--|:--|:--|
| `/api/*` | `BACKEND_URL` | Product APIs, login, settings, task history, gallery. |
| `/images/*` | `BACKEND_URL` | Private signed generated images. |
| `/image-thumbnails/*` | `BACKEND_URL` | Private thumbnails. |
| `/v1/*` | `MODEL_BACKEND_URL` | OpenAI-compatible model calls. |

Do not set `NEXT_PUBLIC_API_BASE_URL` in same-origin proxy mode. Leave browser calls relative so cookies, task restore, and private image URLs stay on the same origin.

## Image Generation Data Flow

```mermaid
sequenceDiagram
  participant U as User
  participant W as happytoken-web
  participant A as happytoken-api
  participant N as NewAPI
  participant M as Upstream model
  participant S as Image storage
  participant T as Task store

  U->>W: Submit prompt on /image
  W->>A: POST /api/image-tasks/generations
  A->>T: Create queued task by owner_id + client_task_id
  A->>N: POST /v1/images/generations
  N->>M: Route to configured provider/account pool
  M-->>N: Image URL or b64_json
  N-->>A: OpenAI-compatible image response
  A->>S: Materialize image into Happy Token storage
  A->>T: Persist success with /images/... URL
  W->>A: GET /api/image-tasks?ids=...
  A-->>W: Restorable task with private image URL
  W->>A: GET /images/... with cookie or image_token
  A-->>W: image/png
  W-->>U: Render generated image
```

Important behavior:

- `client_task_id` makes image task submission idempotent.
- If the gateway returns a temporary remote `data[].url`, Happy Token API downloads and saves it before exposing the result.
- Historical successful images are resynced by `taskId`, so stale or expired URLs can be replaced by the latest task data.
- If the current user has no selected provider with Base URL and API Key, image generation fails clearly instead of falling back to server `.env` credentials or local account pools.

## Authentication And Ownership

```mermaid
flowchart LR
  Login["Access key login or OIDC login"]
  Session["HttpOnly signed session cookie"]
  Identity["Resolved identity<br/>id, role, provider"]
  Tasks["Image tasks<br/>owner_id"]
  Conversations["Web local conversation cache<br/>ownerId"]
  Gallery["User gallery and image index<br/>owner_id"]

  Login --> Session
  Session --> Identity
  Identity --> Tasks
  Identity --> Gallery
  Identity --> Conversations
```

Ownership rules:

- API identity is resolved from Bearer token or signed web session cookie.
- Image task records are keyed by `owner_id`.
- Web conversation cache is scoped by `ownerId`.
- Users can restore only their own image tasks and gallery items.

## Storage Model

```mermaid
flowchart TD
  Config[".env + config.json"]
  AuthStore["Auth/account storage<br/>JSON / SQLite / PostgreSQL / Git"]
  TaskStore["Image task storage<br/>JSON or database"]
  ImageStore["Image storage<br/>local / WebDAV / both"]
  RuntimeData["data/* runtime files"]
  SeedGallery["web public/seed-gallery<br/>external static package"]

  Config --> API["happytoken-api"]
  API --> AuthStore
  API --> TaskStore
  API --> ImageStore
  AuthStore --> RuntimeData
  TaskStore --> RuntimeData
  ImageStore --> RuntimeData
  Web --> SeedGallery
```

Version-control boundary:

| Path | Git policy |
|:--|:--|
| `.env`, `config.json` | Never commit; deployment-specific secrets and settings. |
| `data/images`, `data/image_tasks.json`, `data/auth_keys.json`, `data/accounts.json`, logs | Never commit; runtime data and secrets. |
| `happytoken-web/public/seed-gallery/*` | Do not commit; generated or mounted official gallery static package. |
| `.next`, `.open-next`, `out`, `.pytest_cache`, `__pycache__`, `.worktrees` | Generated or temporary; safe to delete. |

## Deployment Modes

### Local Development

```mermaid
flowchart LR
  Browser["http://localhost:3000"]
  Web["happytoken-web pnpm dev"]
  API["happytoken-api uv run python main.py"]
  Gateway["Configured MODEL_BACKEND_URL / NewAPI"]

  Browser --> Web
  Web -->|"BACKEND_URL=http://127.0.0.1:8000"| API
  Web -->|"MODEL_BACKEND_URL"| Gateway
  API -->|"selected user provider Base URL"| Gateway
```

Use:

```bash
BACKEND_URL=http://127.0.0.1:8000
MODEL_BACKEND_URL=https://newapi.example.com/v1
MODEL_BACKEND_API_KEY=<newapi-token>
NEXT_PUBLIC_EXTERNAL_MODEL_ADMIN=true
```

Keep `NEXT_PUBLIC_API_BASE_URL` empty.

### Production Split Deployment

```mermaid
flowchart LR
  Browser["https://image.example.com"]
  Web["happytoken-web"]
  API["https://api.example.com"]
  NewAPI["https://newapi.example.com/v1"]

  Browser --> Web
  Web -->|"BACKEND_URL=https://api.example.com"| API
  Web -->|"MODEL_BACKEND_URL=https://newapi.example.com/v1"| NewAPI
  API -->|"selected user provider Base URL"| NewAPI
```

Set stable public URLs:

```bash
HAPPYTOKEN_FRONTEND_BASE_URL=https://image.example.com
HAPPYTOKEN_API_BASE_URL=https://api.example.com
HAPPYTOKEN_CORS_ORIGINS=https://image.example.com
```

## Verification Checklist

```bash
uv run pytest -q test/test_config.py test/test_image_task_service.py test/test_image_tasks_api.py test/test_newapi_gateway_chain.py
pnpm run test:unit
pnpm exec tsc --noEmit
WEB_URL=http://127.0.0.1:3000 API_URL=http://127.0.0.1:8000 HAPPYTOKEN_USER_TOKEN=<token> ./scripts/verify-newapi-model-chain.sh
```

Browser smoke:

1. Open `/image`.
2. Generate one image.
3. Confirm task reaches `已完成`.
4. Confirm the result renders as an image, not `图片无法加载`.
5. Reload `/image`; confirm the same historical result still renders.
