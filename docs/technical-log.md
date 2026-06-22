# Technical Log

This log records production-impacting bugs, root causes, fixes, and verification steps. Read it before starting a new debugging session so repeated issues do not get rediscovered from scratch.

## How To Add An Entry

Use this format:

```markdown
## YYYY-MM-DD - Short Title

**Symptoms**
- What the user saw.

**Root Cause**
- The concrete failing assumption, config, code path, or dependency.

**Fix**
- Files or settings changed.

**Verification**
- Commands, browser checks, or smoke tests that proved the fix.

**Follow-up**
- Optional remaining risk or future cleanup.
```

## 2026-06-21 - Generated Images Showed "图片无法加载"

**Symptoms**
- The image task completed successfully in `/image`.
- The result card showed `图片无法加载`.
- Task data contained a remote upstream URL such as `https://chatgpt2api.happy-token.cn/images/...png`.

**Root Cause**
- NewAPI returned `data[].url` pointing at an upstream temporary image host.
- The browser and local server could not reliably fetch that host; one direct probe failed with TLS, and older historical links later returned 401.
- Happy Token stored and replayed that upstream URL directly, so the UI depended on an external temporary image host instead of Happy Token storage.

**Fix**
- `services/image_task_service.py`
  - Added gateway output materialization.
  - For gateway `data[].url`, Happy Token downloads the image and saves it through `image_storage_service.save`.
  - For gateway `data[].b64_json`, Happy Token decodes and saves it through the same storage path.
  - Public task data now returns Happy Token `/images/...` URLs and preserves the original upstream URL as `source_url`.
- `test/test_image_task_service.py`
  - Added coverage for remote gateway URL materialization.

**Verification**
- `uv run pytest -q test/test_image_task_service.py test/test_image_tasks_api.py test/test_newapi_gateway_chain.py`
- `scripts/verify-newapi-model-chain.sh`
- Direct image URL check returned `200 image/png`.

**Follow-up**
- Some older upstream URLs cannot be repaired after they expire or return 401. Those historical results need regeneration if they were never materialized.

## 2026-06-21 - Image Still Failed After API Materialization

**Symptoms**
- Backend task data had been repaired to a local `/images/...` URL.
- Browser still showed `图片无法加载`.
- Reloading the page did not update the visible historical result.

**Root Cause**
- `happytoken-web` restored image conversations from localforage.
- History sync only fetched backend tasks for images in `loading` or selected `error` states.
- Images already marked `success` were skipped, so stale successful images kept their old remote URL forever.

**Fix**
- `happytoken-web/src/app/image/page.tsx`
  - `syncConversationImageTasks` now fetches backend task state for every image with `taskId`, not only `loading` / `error` images.
  - Successful images can now receive refreshed URLs, feedback, duration, and task metadata from Happy Token API.

**Verification**
- `pnpm run test:unit`
- `pnpm exec tsc --noEmit`
- Browser reload on `http://localhost:3000/image` showed the generated image rendered with a `blob:http://localhost:3000/...` source.

## 2026-06-21 - Same-Origin Proxy Misconfigured As Cross-Origin

**Symptoms**
- Browser page was opened at `http://localhost:3000/image`.
- Web was started with `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:3000`.
- History sync and private image loads did not behave like same-origin calls.

**Root Cause**
- `localhost` and `127.0.0.1` are different browser origins.
- Setting `NEXT_PUBLIC_API_BASE_URL` forced browser requests away from relative same-origin URLs, bypassing the intended middleware path and exposing requests to cross-origin cookie/CORS behavior.
- Web development defaults previously fell back to `http://127.0.0.1:8000`, which made this mistake easy.

**Fix**
- `happytoken-web/src/constants/common-env.ts`
  - Default `apiUrl` is now empty, so browser calls use relative same-origin paths by default.
- `happytoken-web/README.md`
  - Documents that same-origin proxy mode should leave `NEXT_PUBLIC_API_BASE_URL` empty.
  - Documents `BACKEND_URL` for app routes and `MODEL_BACKEND_URL` / `MODEL_BACKEND_API_KEY` for model routes.

**Verification**
- Web was restarted without `NEXT_PUBLIC_API_BASE_URL`.
- Browser reload on `http://localhost:3000/image` removed `图片无法加载`.
- The generated image rendered with natural dimensions `1254x1254`.
- `pnpm run test:unit`
- `pnpm exec tsc --noEmit`

## 2026-06-21 - Model Gateway Key Needed Redaction

**Symptoms**
- Model gateway token needed to be configurable through API settings and environment variables.
- The settings response could not expose the raw token.

**Root Cause**
- Gateway configuration lived alongside other runtime settings, but token handling needed different semantics:
  - environment variable override should win,
  - blank token saves should preserve the previous token,
  - API responses should only report whether a token is configured.

**Fix**
- `services/config.py`
  - Added model gateway settings, environment override handling, and token redaction.
- API settings now returns `model_gateway_api_key_configured` instead of raw `model_gateway_api_key`.

**Verification**
- `/api/settings` returned:
  - configured gateway URL,
  - `model_gateway_api_key_configured: true`,
  - no raw `model_gateway_api_key`.
- `uv run pytest -q test/test_config.py`

## 2026-06-21 - User Provider Gateway Should Not Fall Back Silently

**Symptoms**
- After moving account pool and reverse-engineered GPT image calls out to NewAPI, Happy Token should not silently fall back to local account-pool generation or server `.env` gateway credentials when the current user has not configured a provider.

**Root Cause**
- Image tasks could still use local handlers or server-level gateway configuration instead of the current user's selected provider.

**Fix**
- Image tasks now require the current user's selected provider Base URL and API Key.
- `services/model_gateway_service.py` raises a clear configuration error when the user provider is missing.
- `/api/image-tasks/*` persists the failure as a restorable error task instead of leaving the UI ambiguous.

**Verification**
- `uv run pytest -q test/test_image_task_service.py::ImageTaskServiceTests::test_required_gateway_missing_marks_task_error_without_local_fallback`

## 2026-06-21 - MODEL_BACKEND_URL With `/v1` Could Double Prefix

**Symptoms**
- Web middleware had to support both `MODEL_BACKEND_URL=http://host:port` and `MODEL_BACKEND_URL=http://host:port/v1`.
- Without normalization, `/v1/models` could become `/v1/v1/models`.

**Root Cause**
- Web middleware originally joined base URL and request path without checking whether the base already ended in `/v1`.

**Fix**
- `happytoken-web/src/middleware.ts`
  - `buildProxyUrl` strips the incoming `/v1` prefix when `MODEL_BACKEND_URL` already ends with `/v1`.
  - `/v1/*` proxy requests use an allowlisted header set and inject `MODEL_BACKEND_API_KEY` server-side.

**Verification**
- Web middleware unit tests cover both base URL forms.
- `pnpm run test:unit`

## 2026-06-21 - Official Gallery Should Not Inflate API Docker Image

**Symptoms**
- Official gallery images are public static assets, but API Docker copied `data/image-gallery-seed` into the image and initialized it into `/app/data`.
- The seed gallery directory is large and should not be committed or bundled into default deployment artifacts as it grows.

**Root Cause**
- The first gallery implementation served records, images, and thumbnails from `/api/seed-gallery/*`.
- That made API own both product state and public static gallery assets.

**Fix**
- `happytoken-web` now prefers a static gallery package at `public/seed-gallery/static/items.json`.
- Static image URLs use `/seed-gallery/images/*` and `/seed-gallery/thumbnails/w640/*`.
- If the static package is absent, web falls back to the existing `/api/seed-gallery/*` compatibility endpoints.
- API Docker no longer copies `data/image-gallery-seed` or initializes seed gallery data on startup.
- Added `scripts/export_seed_gallery_static.py` to export normalized gallery JSON and optionally copy assets.

**Verification**
- `uv run python scripts/export_seed_gallery_static.py --output ../happytoken-web/public/seed-gallery`
- Exported 3427 items and rewrote image URLs to `/seed-gallery/*`.
- Generated static files are ignored by git and were removed after verification to keep local fallback behavior unchanged.
