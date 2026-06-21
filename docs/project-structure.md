# Project Structure

HappyImage API is organized around FastAPI routes, business services, protocol adapters, and storage backends. Keep new code close to the layer that owns the behavior.

## Top-level Layout

| Path | Purpose |
|:--|:--|
| `api/` | HTTP routing, request parsing, response wiring, auth gates |
| `services/` | Business logic and integrations used by routes |
| `services/protocol/` | OpenAI / Anthropic-compatible protocol adapters |
| `services/storage/` | Account storage backend implementations |
| `utils/` | Shared low-level helpers with minimal app coupling |
| `scripts/` | Operational scripts, migrations, one-off maintenance tools |
| `test/` | Pytest test suite |
| `docs/` | Deployment, architecture, feature, and product notes |
| `data/image-gallery-seed/` | Official gallery source data for export scripts |

## Layering Guidelines

Routes in `api/` should stay thin: validate inputs, resolve identity, call services, and translate errors into HTTP responses.

Business rules belong in `services/`. If logic is reused by multiple routes or needs focused tests, prefer a service module over expanding route handlers.

Protocol translation belongs in `services/protocol/`. Keep compatibility quirks for OpenAI, Anthropic, image generation, search, and editable-file tasks there instead of mixing them into route modules.

Storage-specific behavior belongs in `services/storage/`. New storage backends should implement the shared base contract and be registered through `services/storage/factory.py`.

Shared helpers in `utils/` should avoid importing from `api/` or high-level services. This keeps utility code reusable and easier to test.

## Configuration and Runtime Data

Use `.env` for deployment-specific values such as secrets, public URLs, proxy settings, and storage credentials. Use `config.json` or the Web settings API for application settings that operators may change over time.

Runtime data lives under `data/`. Generated logs, images, task state, databases, local caches, and exported official-gallery static packages should remain untracked.

Generated caches and local work products should stay ignored and can be deleted when cleaning a workspace:

| Path | Notes |
|:--|:--|
| `__pycache__/`, `*/__pycache__/` | Python bytecode cache. |
| `.pytest_cache/` | Pytest local cache. |
| `.worktrees/` | Temporary agent or feature worktrees; remove after merging or abandoning their branches. |
| `.venv/` | Local Python dependency environment; keep if actively developing, otherwise recreate with `uv sync`. |

Do not delete `.env`, `config.json`, or `data/*` during cleanup unless the operator explicitly wants to reset local runtime state. Those files can contain secrets, user history, generated images, and account data.

## Documentation Map

| Document | Purpose |
|:--|:--|
| `README.md` | Main setup, configuration, NewAPI overview, operations commands. |
| `docs/architecture.md` | Mermaid architecture diagrams for deployment, route split, image data flow, auth, and storage. |
| `docs/newapi-gateway.md` | Authoritative NewAPI integration and HappyImage Web model-gateway chain. |
| `docs/technical-log.md` | Bug history, root causes, fixes, and verification notes for future sessions. |
| `docs/docker-deployment.md` | Docker deployment and server operations. |
| `docs/feature-status.en.md` | Feature support matrix. |
| `docs/gallery-curation.md` | Gallery seed and curation workflow. |

## Script Conventions

Scripts in `scripts/` should be safe to run from the repository root with `uv run python scripts/<name>.py` unless the script documents otherwise.

Avoid committing local probe scripts that contain private hosts, account data, auth keys, or proxy credentials. Keep those as ignored local files or turn them into sanitized templates before committing.

## Test Conventions

Tests live in `test/` and are discovered by pytest via `pyproject.toml`.

Prefer focused tests around service behavior for business logic, and API tests when request parsing, authentication, status codes, or response shape matter.

The default test command is:

```bash
uv run pytest
```

Tests marked `live` are skipped by default because they require a running local API service, usually at `localhost:8000`, and may depend on real upstream credentials. Run them explicitly during integration checks:

```bash
uv run pytest -m live
```
