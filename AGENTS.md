# Happy Token

OpenAI-compatible image API and self-hosted creation workspace.

## Deployment Notes

- Project type: web app + API
- Runtime: Docker
- Service name: `happytoken`
- Required secret: `HAPPYTOKEN_SESSION_SECRET`
- Example health check: `curl -sf http://localhost:3000/health?format=json`
- Docker deployment guide: `docs/docker-deployment.md`

Keep production hosts, remote aliases, service paths, auth keys, and account data outside git. Use `.env` and `config.json` from `config.example.json` for local or server-specific configuration.

## Build Notes

- Dockerfile uses China-friendly mirrors:
  - Debian: `mirrors.aliyun.com`
  - npm: `registry.npmmirror.com`
  - pip: `mirrors.aliyun.com/pypi/simple/`
- PyPI uses the Aliyun mirror via `pyproject.toml`.
