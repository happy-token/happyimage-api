# Happy Token

OpenAI-compatible image API and self-hosted creation workspace.

## Deployment Notes

- Project type: API service
- Runtime: Docker
- Service name: `happytoken`
- Runtime settings such as `session_secret`, `session_cookie_domain`, `public_app_url`, `api_public_url`, and `cors_origins` are managed through `config.json`, first-run `/setup`, or admin `/settings`.
- Example API health check: `curl -sf http://localhost:8000/health?format=json`
- Docker deployment guide: `docs/docker-deployment.md` (API-only). Combined Web/API HS integration uses `deploy/hs/docker-compose.yml` in this repository.

Keep production hosts, remote aliases, service paths, auth keys, and account data outside git. Keep deployment `.env` files infrastructure-only; use `config.json` from `config.example.json`, `/setup`, or admin `/settings` for runtime application configuration.

## Build Notes

- Dockerfile uses China-friendly mirrors:
  - Debian: `mirrors.aliyun.com`
  - npm: `registry.npmmirror.com`
  - pip: `mirrors.aliyun.com/pypi/simple/`
- PyPI uses the Aliyun mirror via `pyproject.toml`.
