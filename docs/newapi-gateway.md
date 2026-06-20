# NewAPI Gateway

HappyImage exposes OpenAI-compatible endpoints and can be registered in NewAPI as a custom OpenAI-compatible channel.

## Upstream Configuration

In NewAPI, create a channel with:

- Type: OpenAI-compatible or custom OpenAI API
- Base URL: `https://<happyimage-api-host>/v1`
- API key: a HappyImage user key or `HAPPYIMAGE_AUTH_KEY`
- Models: `gpt-image-2` and any text models returned by `GET /v1/models`

NewAPI should send requests with:

```http
Authorization: Bearer <happyimage-key>
```

HappyImage currently supports these OpenAI-compatible routes:

- `GET /v1/models`
- `POST /v1/images/generations`
- `POST /v1/images/edits`
- `POST /v1/chat/completions`
- `POST /v1/responses`

## happyimage-web Through NewAPI

`happyimage-web` can call NewAPI instead of HappyImage directly for image generation if it uses NewAPI's OpenAI-compatible base URL and a NewAPI token:

- Base URL: `https://<newapi-host>/v1`
- API key: the NewAPI token assigned to the user or project
- Image endpoint: `/images/generations` or `/images/edits`

For browser login, user gallery, image-task history, recharge callbacks, and private image links, keep calling HappyImage's own `/api/*` routes. NewAPI should be used as the model gateway, not as the HappyImage application backend.

## Notes

- Configure `HAPPYIMAGE_API_BASE_URL` when HappyImage is behind a reverse proxy. OIDC redirect URIs and generated image URLs need a stable public API origin.
- Use a normal HappyImage user key for NewAPI channels if you want per-channel image quota accounting.
- The health check is `GET /health?format=json`.
