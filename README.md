<h1 align="center">HappyImage API</h1>

<p align="center">Product-state API for HappyImage: auth, user data, image task history, private image storage, setup, and admin-managed runtime settings.</p>

HappyImage API 是 HappyImage 的 FastAPI 产品后端，负责登录、用户会话、图片任务历史、用户图库、私有图片访问、日志、设置和 NewAPI/HappyToken 绑定。模型账号池、上游调试、充值/额度和 token 路由由 NewAPI 等外部模型网关管理；官方图库图片作为 Web 静态包维护，不再由 API 镜像承载。

> [!WARNING]
> 免责声明：
>
> 本项目涉及对 ChatGPT 官网文本生成、图片生成与图片编辑等相关接口的逆向研究，仅供个人学习、技术研究与非商业性技术交流使用。
>
> - 严禁将本项目用于任何商业用途、盈利性使用、批量操作、自动化滥用或规模化调用。
> - 严禁将本项目用于破坏市场秩序、恶意竞争、套利倒卖、二次售卖相关服务，以及任何违反 OpenAI 服务条款或当地法律法规的行为。
> - 使用者应自行承担全部风险，包括但不限于账号被限制、临时封禁或永久封禁以及因违规使用等所导致的法律责任。

## 功能概览

- 图片任务接口：文生图 / 图生图任务创建、轮询、历史恢复和用户图库物化
- Web 产品接口：登录、OIDC、用户密钥、日志、设置、图片任务历史、用户图库、分享草稿
- 首次设置：`/api/setup/*` 用于初始化公开 URL、会话、OIDC、模型网关和存储配置
- NewAPI 绑定：OIDC 登录后可通过 provisioning endpoint 或 SQL 直连创建/复用 NewAPI 用户和 token
- 认证：管理员访问密钥、用户 Bearer token、OIDC 单点登录、HttpOnly Cookie 会话
- 存储：JSON、SQLite、PostgreSQL
- 部署：Docker / Docker Compose，镜像构建使用 China-friendly mirrors

HappyImage API 不再暴露 HappyImage-owned `/v1/*` 兼容入口。产品图片工作台使用 `/api/image-tasks/*`；API 内部再按当前用户选中的供应商 Base URL 调用上游 OpenAI-compatible provider，例如 `https://gateway.happy-token.cn/v1`。

## 职责边界

| 模块 | 负责 | 不负责 |
|:--|:--|:--|
| `happyimage-api`（本仓库） | 产品后端、认证会话、用户、图片任务历史、用户图库、私有图片访问、设置、日志、NewAPI 绑定 | 前端页面渲染、官方图库静态资源发布、NewAPI 账号池管理、充值/额度、外部模型协议兼容入口 |
| `happyimage-web` | Next.js 前端、同源 middleware、用户工作台、官方图库静态包读取 | 用户历史/私有图库持久化、API 数据库、模型账号池、模型协议代理 |
| `happyimage-gallery-source` | 官方图库源数据和候选池，供 Web 静态包导出 | 运行时服务、GitHub 版本化发布 |
| NewAPI / 模型网关 | 模型渠道、账号池、上游调试、token、额度/计费路由 | HappyImage 用户登录、历史会话、用户图库、私有图片 |

推荐链路：

```text
Browser -> happyimage-web
  /api/*, /images/*, /image-thumbnails/*, /health -> happyimage-api
  /seed-gallery/*                                 -> happyimage-web static assets

happyimage-api /api/image-tasks/* -> selected user provider Base URL
happyimage-api                    -> stores user, history, gallery, private image refs
```

## 快速开始

```bash
git clone git@github.com:happy-token/happyimage-api.git
cd happyimage-api
cp config.example.json config.json
docker compose up -d
curl -sf http://localhost:8000/health?format=json
```

默认端口：

| 服务 | 地址 |
|:--|:--|
| API | `http://localhost:8000` |
| 健康检查 | `http://localhost:8000/health?format=json` |

默认启动不需要 `.env`。只有要覆盖端口、镜像、存储后端或 `DATABASE_URL` 时，才复制 `.env.example` 为 `.env`。首次部署后，使用 `/setup` 或 Web 管理设置页维护公开地址、会话密钥、OIDC、NewAPI 绑定、模型网关、图片存储、代理和安全设置。不要把这些运行时设置放回 Docker Compose 或 `.env.example`。

## 本地开发

本项目使用 Python 3.13 和 `uv`。

```bash
git clone git@github.com:happy-token/happyimage-api.git
cd happyimage-api
cp config.example.json config.json
uv sync
uv run python main.py
```

运行测试：

```bash
uv run pytest
```

默认测试套件会跳过需要已启动本地服务和真实上游凭据的 live smoke 测试。如需联调已运行的 `localhost:8000` 服务：

```bash
uv run pytest -m live
```

## 配置模型

配置分两层：

| 层级 | 文件 / 入口 | 放什么 |
|:--|:--|:--|
| 基础设施覆盖，可选 | `.env` | 端口、镜像、`STORAGE_BACKEND`、`DATABASE_URL`、构建基础镜像 |
| 应用运行时设置 | `config.json`、首次 `/setup`、Web 管理设置页 | 公开 URL、会话密钥、OIDC、模型网关、NewAPI 绑定、图片存储、审核和安全设置 |

默认本地或测试启动只需要复制 `config.example.json` 为 `config.json`。`.env` 不是必需文件。

部署环境变量只保留基础设施项：

| 变量 | 说明 |
|:--|:--|
| `STORAGE_BACKEND` | 存储后端，生产环境推荐 `postgres` |
| `DATABASE_URL` | PostgreSQL / SQLite 连接地址；数据库存储时使用 |
| `HAPPYTOKEN_API_PORT` | Compose 端口映射使用的宿主机端口 |
| `HAPPYTOKEN_PYTHON_IMAGE` | Docker 构建基础 Python 镜像覆盖 |

管理员运行时设置放在 `config.json`、首次 `/setup` 或 Web 管理设置页：

| 设置 | 字段 |
|:--|:--|
| Public app URL | `public_app_url` |
| Optional API public URL | `api_public_url` |
| Session / cookie | `session_secret`、`session_cookie_name`、`session_cookie_domain`、`session_max_age_seconds` |
| OAuth / OIDC | `oidc.enabled`、`issuer`、`client_id`、`client_secret`、`scopes`、`allowed_email_domains` |
| Model gateway URLs | `model_gateway.gateway_api_base_url`、`model_gateway.gateway_management_url` |
| NewAPI binding | `model_gateway.provision_url`、`provision_secret`、`sql_dsn`、`token_name` |
| Proxy | `proxy` |
| Image storage | `image_storage.*`、`image_retention_days`、`image_access_token_ttl_seconds` |
| Safety settings | `sensitive_words`、`ai_review.*`、`global_system_prompt` |

`config.example.json` 只提供初始字段和默认值，避免容器启动时把挂载目标创建成目录。首次 `/setup` 或管理员设置保存后，以当前运行时配置为准。

`config.example.json` uses the current field names:

```json
{
  "public_app_url": "",
  "api_public_url": "",
  "model_gateway": {
    "gateway_api_base_url": "https://gateway.happy-token.cn/v1",
    "gateway_management_url": "https://gateway.happy-token.cn",
    "provision_url": "",
    "provision_secret": "",
    "sql_dsn": "",
    "token_name": "HappyImage Default"
  }
}
```

## Removed Variable Migration

| Removed variable | New home |
|:--|:--|
| `MODEL_BACKEND_URL` | `model_gateway.gateway_api_base_url` in API runtime settings; user generation uses selected provider Base URL |
| `MODEL_BACKEND_API_KEY` | Default/user provider API key managed by HappyImage API; NewAPI binding secrets live under `model_gateway.*` |
| `NEXT_PUBLIC_MODEL_API_BASE_URL` | Removed with Web `/v1/*` proxying |
| `HAPPYTOKEN_FRONTEND_BASE_URL` | `public_app_url` |
| `HAPPYTOKEN_API_BASE_URL` | `api_public_url` |
| `HAPPYTOKEN_CORS_ORIGINS` | `cors_origins` or derived from `public_app_url` |
| `HAPPYTOKEN_NEWAPI_BASE_URL` | `model_gateway.gateway_api_base_url` |
| `HAPPYTOKEN_NEWAPI_MANAGEMENT_URL` | `model_gateway.gateway_management_url` |

## 图片任务 API

HappyImage 提供产品任务接口，负责历史 session、用户图库、私有图片签名和下载管理。

| 生图类型 | 产品任务接口 |
|:--|:--|
| 文生图 | `POST /api/image-tasks/generations` |
| 图生图 / 图片编辑 | `POST /api/image-tasks/edits` |

文生图任务示例：

```bash
curl http://localhost:8000/api/image-tasks/generations \
  -H "Authorization: Bearer <HappyImage user token>" \
  -H "Content-Type: application/json" \
  -d '{
    "client_task_id": "demo-generation-001",
    "model": "gpt-image-2",
    "prompt": "a small product photo on a white table",
    "size": "1024x1024",
    "quality": "auto"
  }'
```

图生图 / 图片编辑任务示例：

```bash
curl http://localhost:8000/api/image-tasks/edits \
  -H "Authorization: Bearer <HappyImage user token>" \
  -F client_task_id=demo-edit-001 \
  -F model=gpt-image-2 \
  -F prompt="change the background to a clean studio scene" \
  -F size=1024x1024 \
  -F quality=auto \
  -F image=@./reference.png
```

如果提示词明确要求参考图、上传图、人脸身份保持或源图，但请求没有上传图片，应该使用图生图接口并附带 `image`。纯文生图接口不会自动补充参考图。

图片生成只使用当前用户在 Web“我的 -> 供应商”中选中的 Base URL 和 API Key。默认 HappyToken 供应商由登录绑定流程生成，充值、余额、额度和计费由 NewAPI 或外部模型供应商负责。

## NewAPI / HappyToken Binding

普通用户建议通过 Casdoor OIDC 登录。OIDC 回调创建或复用本地 HappyImage 用户后，会尝试通过 `model_gateway` 配置创建或复用 NewAPI 用户/token，并把它写成用户默认 HappyToken 供应商。

绑定方式二选一：

| 方式 | 字段 |
|:--|:--|
| Provisioning endpoint | `model_gateway.provision_url` + `model_gateway.provision_secret` |
| Direct SQL provisioning | `model_gateway.sql_dsn` |

如果两种方式都未配置完整，OIDC 登录仍会成功，用户 session 会报告 `newapi_binding_status=pending`。`/api/auth/session` 会在用户已有 OIDC 身份但绑定仍是 pending/failed 时重试。

`/api/auth/newapi-management` 是 `/settings/newapi` 使用的认证产品接口；它返回绑定状态、NewAPI user ID、token 列表、默认 API Key 和外部管理 URL。

## 运行数据、图片和迁移

Docker 部署时，容器内 `/app/data` 会挂载到仓库目录下的 `./data`。本地开发时也默认使用仓库里的 `data/`。这个目录是运行数据目录，不是普通源码目录。

| 路径 | 内容 | 是否应提交到 git |
|:--|:--|:--|
| `data/images/` | 用户生成的原图，按日期分目录保存 | 否 |
| `data/image_thumbnails/` | 用户生成图片的缩略图缓存 | 否，可重新生成 |
| `data/image_index.json` | 本地图片索引和图片存储记录 | 否 |
| `data/image_tasks.json` | 图片任务状态 | 否 |
| `data/auth_keys.json`、`data/accounts.db` | 用户密钥、用户数据或数据库文件 | 否，敏感 |
| `data/logs.jsonl`、`data/share_drafts.json`、`data/image_tags.json` | 日志、分享草稿、图片标签 | 否，可能敏感 |
| `../happyimage-gallery-source/image-gallery-seed/` | 官方图库源数据 | 仓库外保存；生产使用 Web 静态包 |

升级前建议备份 `config.json` 和 `data/`。生产主机、远程路径、密钥和第三方令牌不要提交到 git；基础设施覆盖才放 `.env`，应用运行时设置放 `config.json`、`/setup` 或管理设置页。

## Docker 镜像

`main` 分支推送后，GitHub Actions 会构建并发布多架构 API 镜像到 GitHub Container Registry：

```bash
docker pull ghcr.io/happy-token/happyimage-api:latest
```

如果使用工作区根目录的 Web + API 组合部署，默认会同时拉取：

```bash
docker pull ghcr.io/happy-token/happyimage-api:latest
docker pull ghcr.io/happy-token/happyimage-web:latest

cd /opt/happytoken/happyimage
mkdir -p data/api data/seed-gallery
test -f data/config.json || cp happyimage-api/config.example.json data/config.json
docker compose -f deploy/hs/docker-compose.yml pull
docker compose -f deploy/hs/docker-compose.yml up -d
```

如果 GHCR package 不是公开可读，需要先在目标机器登录：

```bash
docker login ghcr.io
```

当前 workflow 位于 `.github/workflows/docker-publish.yml`，支持 `linux/amd64` 和 `linux/arm64`。打 `v*` tag 时会额外发布版本标签。

Dockerfile 使用 China-friendly mirrors：

- Debian：`mirrors.aliyun.com`
- PyPI：`mirrors.aliyun.com/pypi/simple/`

更多部署说明见 [Docker 部署指南](docs/docker-deployment.md)。技术架构图见 [Architecture](docs/architecture.md)。更多分层和维护约定见 [项目结构说明](docs/project-structure.md)。重大故障、根因和修复记录见 [技术日志](docs/technical-log.md)。
