# NewAPI Gateway

HappyImage uses NewAPI as an upstream model gateway and HappyToken management surface. NewAPI is not the HappyImage application backend. Login, OIDC, history, user gallery, private image URLs, settings, and logs must keep using HappyImage `/api/*` routes.

For the visual architecture and data-flow diagrams, see [Architecture](architecture.md).

## Current Boundary

HappyImage API and Web no longer expose or proxy external compatibility routes. Product image generation uses:

```text
Browser -> happyimage-web /api/image-tasks/*
  -> happyimage-api task/history/gallery storage
  -> current user's selected provider Base URL
  -> upstream OpenAI-compatible model gateway, usually NewAPI
```

`/v1` appears in this documentation only as part of an upstream provider URL, such as `https://gateway.happy-token.cn/v1`.

## HappyImage API Provider Configuration

HappyImage API does not use `.env` model-gateway variables as a fallback for image generation. Normal users get a default HappyToken provider after Casdoor OIDC login. That provider is backed by a NewAPI user token created during binding, is selected by default, and cannot be deleted from the Web supplier list.

Users can add extra providers from the Web supplier picker:

| Provider | Configuration in Web |
|:--|:--|
| HappyToken | Auto-bound default provider; open `/settings/newapi` to view binding status and default API Key. |
| OpenAI | API Key only; Base URL and model presets are provided by the app. |
| Gemini / Nano Banana | API Key only; UI labels include `gemini-3.1-flash-image（Nano Banana 2）`, `gemini-3-pro-image（Nano Banana Pro）`, `gemini-2.5-flash-image（Nano Banana）`. |
| 火山方舟 / BytePlus ModelArk / 阿里云百炼 | API Key only; Base URL and presets are provided by the app. |
| Custom provider | Name, Base URL, model list and API Key. |

The protocol field is currently stored internally as OpenAI-compatible and is not shown in the Web form. The shared image-generation path sends OpenAI Images API style requests to the selected provider Base URL. Providers that do not expose compatible image endpoints need a provider-specific adapter before they can work end to end.

If the current user has no selected provider with both Base URL and API Key, `/api/image-tasks/*` fails clearly instead of falling back to a server `.env` provider or the old local account pool.

Successful gateway image outputs are materialized into HappyImage storage. When NewAPI returns a remote `data[].url`, HappyImage API downloads it, saves it through `image_storage_service`, and returns a private `/images/...` URL. This keeps generated images restorable even if the upstream temporary image host is blocked or expires.

## HappyToken Management Page

`/settings/newapi` is the product management entry for the default HappyToken provider. It calls HappyImage API `/api/auth/newapi-management` with the current HappyImage session and displays the binding status, NewAPI user ID, default API Key and token list.

This page should not depend on an embedded NewAPI admin session. SQL/provisioning creates NewAPI database records and tokens, but it does not write a `gateway.happy-token.cn` browser `session` cookie. Because that cookie belongs to another origin and can be affected by frame and SameSite policies, direct NewAPI admin pages can show “not logged in” while HappyImage binding and model calls are already configured.

If users see `NewAPI SQL provisioning request failed`, check the returned binding status first:

- `configured`: the default HappyToken provider is ready; the message is stale UI state and should be cleared by the Web session refresh.
- `pending` or `failed`: login can still succeed, but the default HappyToken API Key may be missing or unusable until NewAPI SQL/provisioning is fixed.

## Admin Runtime Settings

NewAPI/HappyToken binding is configured in `config.json`, first setup, or the Web admin settings page:

| Field | Purpose |
|:--|:--|
| `model_gateway.gateway_api_base_url` | Upstream model API base URL, usually `https://gateway.happy-token.cn/v1` |
| `model_gateway.gateway_management_url` | External management URL, usually `https://gateway.happy-token.cn` |
| `model_gateway.provision_url` | Optional controlled provisioning endpoint |
| `model_gateway.provision_secret` | Provisioning endpoint secret |
| `model_gateway.sql_dsn` | Optional direct NewAPI database DSN |
| `model_gateway.token_name` | Token name created/reused for the default HappyToken provider |

## Verification

Unit and contract tests:

```bash
uv run pytest -q test/test_config.py test/test_image_tasks_api.py test/test_newapi_binding_service.py test/test_v1_routes_removed.py
```

Browser smoke:

1. Open `/image`.
2. Generate one image.
3. Confirm the task reaches `已完成`.
4. Confirm the result renders as an image, not `图片无法加载`.
5. Reload `/image`; confirm the same historical result still renders.

## Production Notes

- Store runtime application settings in `config.json` or admin settings, not deployment env.
- Keep `.env`, `config.json`, and `data/*` outside git. They can contain user keys, upstream account tokens, session secrets, image data, and private logs.
- Use PostgreSQL or SQLite for persistent account and task storage when users must recover history after login.
