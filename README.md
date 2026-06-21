<h1 align="center">HappyImage API</h1>

<p align="center">OpenAI-compatible image API and self-hosted creation workspace backend.</p>

HappyImage API 是 HappyImage 的 FastAPI 后端，提供 OpenAI 兼容的图片生成 / 图片编辑接口、Chat Completions / Responses / Anthropic Messages 兼容入口、账号池管理、用户密钥、OIDC 登录、图库、日志、图片归档和备份能力。

> [!WARNING]
> 免责声明：
>
> 本项目涉及对 ChatGPT 官网文本生成、图片生成与图片编辑等相关接口的逆向研究，仅供个人学习、技术研究与非商业性技术交流使用。
>
> - 严禁将本项目用于任何商业用途、盈利性使用、批量操作、自动化滥用或规模化调用。
> - 严禁将本项目用于破坏市场秩序、恶意竞争、套利倒卖、二次售卖相关服务，以及任何违反 OpenAI 服务条款或当地法律法规的行为。
> - 使用者应自行承担全部风险，包括但不限于账号被限制、临时封禁或永久封禁以及因违规使用等所导致的法律责任。
> - 本项目基于对 ChatGPT 官网相关能力的逆向研究实现，存在账号受限、临时封禁或永久封禁的风险。请勿使用自己的重要账号、常用账号或高价值账号进行测试。

## 功能概览

- OpenAI 兼容接口：`/v1/models`、`/v1/images/generations`、`/v1/images/edits`、`/v1/chat/completions`、`/v1/responses`
- Anthropic Messages 兼容入口：`/v1/messages`
- 扩展任务接口：搜索、PPT / PSD 生成任务、图片任务轮询
- Web 管理接口：账号池、用户密钥、额度、日志、设置、图片库、图库种子、分享草稿
- 认证：管理员访问密钥、用户 Bearer token、OIDC 单点登录、HttpOnly Cookie 会话
- 存储：JSON、SQLite、PostgreSQL、Git 后端
- 部署：Docker / Docker Compose，镜像构建使用 China-friendly mirrors

## 仓库结构

| 路径 | 说明 |
|:--|:--|
| `api/` | FastAPI 路由和请求解析 |
| `services/` | 业务服务、协议适配、存储后端 |
| `data/image-gallery-seed/` | 内置图库种子数据和缩略图 |
| `scripts/` | 迁移、测试、部署和容器启动脚本 |
| `docs/` | 部署、功能状态和产品研究文档 |
| `config.example.json` | 应用配置模板 |
| `.env.example` | Docker / 环境变量模板 |

技术架构图见 [Architecture](docs/architecture.md)。更多分层和维护约定见 [项目结构说明](docs/project-structure.md)。重大故障、根因和修复记录见 [技术日志](docs/technical-log.md)；开始新的排障 session 前建议先读该日志。

## 关联项目

| 仓库 | 说明 |
|:--|:--|
| **happyimage-api**（本仓库） | FastAPI 后端：API、OIDC 回调、会话管理、号池管理 |
| [happyimage-web](https://github.com/happy-token/happyimage-web) | 前端：Next.js Web 面板 |
| [HappyImage（旧 monorepo）](https://github.com/happy-token/HappyImage) | 旧合并仓库（存档） |

当前 `docker-compose.yml` 启动的是 API 服务。前端可单独部署 `happyimage-web`，也可以在镜像或运行环境中提供前端静态产物；后端会在存在 Web assets 时尝试托管静态页面。

## Docker 镜像

`main` 分支推送后，GitHub Actions 会构建并发布多架构 API 镜像到 GitHub Container Registry：

```bash
docker pull ghcr.io/happy-token/happyimage-api:latest
```

当前 workflow 位于 `.github/workflows/docker-publish.yml`，支持 `linux/amd64` 和 `linux/arm64`。打 `v*` tag 时会额外发布版本标签。

## 快速开始

### Docker Compose

```bash
git clone git@github.com:happy-token/happyimage-api.git
cd happyimage-api
cp .env.example .env
cp config.example.json config.json
```

编辑 `.env`，至少设置：

```bash
HAPPYIMAGE_AUTH_KEY=replace_with_a_strong_secret
HAPPYIMAGE_SESSION_SECRET=generate-a-random-secret-at-least-32-chars
```

启动：

```bash
docker compose up -d --build
docker compose ps
curl -sf http://localhost:8000/health?format=json
```

默认端口：

| 服务 | 地址 |
|:--|:--|
| API | `http://localhost:8000` |
| OpenAI-compatible base URL | `http://localhost:8000/v1` |
| 健康检查 | `http://localhost:8000/health?format=json` |

### 本地开发

本项目使用 Python 3.13 和 `uv`。

```bash
git clone git@github.com:happy-token/happyimage-api.git
cd happyimage-api
cp config.example.json config.json
export HAPPYIMAGE_AUTH_KEY=replace_with_a_strong_secret
uv sync
uv run python main.py
```

本地开发默认监听 `http://127.0.0.1:8000`。

运行测试：

```bash
uv run pytest
```

默认测试套件会跳过需要已启动本地服务和真实上游凭据的 live smoke 测试。如需联调已运行的 `localhost:8000` 服务：

```bash
uv run pytest -m live
```

## 配置

推荐把密钥、代理、部署域名放到 `.env`，把功能开关和运行参数放到 `config.json` 或 Web 设置页。环境变量会覆盖 `config.json` 中的同类配置。

### 必填

| 变量 | 说明 |
|:--|:--|
| `HAPPYIMAGE_AUTH_KEY` | 管理员认证密钥，也是默认管理员恢复登录密钥 |
| `HAPPYIMAGE_SESSION_SECRET` | Web 登录会话签名密钥，建议至少 32 字符，生产环境必须稳定保存 |

### 服务地址与 CORS

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `HAPPYIMAGE_BASE_URL` | 对外基础 URL，影响图片绝对地址 | 空 |
| `HAPPYIMAGE_FRONTEND_BASE_URL` | 前端公开地址，OIDC 登录后重定向目标 | 空 |
| `HAPPYIMAGE_API_BASE_URL` | 后端公开地址，用于构造 OIDC 回调 URL | `HAPPYIMAGE_BASE_URL` |
| `HAPPYIMAGE_CORS_ORIGINS` | 允许的跨域来源，逗号分隔 | `HAPPYIMAGE_FRONTEND_BASE_URL` |
| `HAPPYIMAGE_MODEL_GATEWAY_BASE_URL` | 可选 OpenAI-compatible 模型网关地址，例如 NewAPI 的 `/v1` | 空 |
| `HAPPYIMAGE_MODEL_GATEWAY_API_KEY` | 可选模型网关 API Key，例如 NewAPI token | 空 |

`HAPPYIMAGE_MODEL_GATEWAY_*` 也可以在管理员系统设置中保存；如果 `.env` 或部署环境变量里已经配置，环境变量优先。设置页面中的 token 留空保存会保留原有 token，不会清空。

### 会话与 OIDC

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `HAPPYIMAGE_SESSION_SECRET` | 会话签名密钥，Web 登录和 OIDC 登录必需 | 空 |
| `HAPPYIMAGE_SESSION_COOKIE_NAME` | 会话 Cookie 名称 | `happyimage_session` |
| `HAPPYIMAGE_SESSION_MAX_AGE_SECONDS` | 会话过期时间（秒） | `86400` |
| `HAPPYIMAGE_OIDC_ENABLED` | 是否启用 OIDC | `false` |
| `HAPPYIMAGE_OIDC_ISSUER` | OIDC issuer URL | 空 |
| `HAPPYIMAGE_OIDC_CLIENT_ID` | OAuth Client ID | 空 |
| `HAPPYIMAGE_OIDC_CLIENT_SECRET` | OAuth Client Secret | 空 |
| `HAPPYIMAGE_OIDC_SCOPES` | OIDC scopes | `openid profile email` |
| `HAPPYIMAGE_OIDC_ALLOWED_EMAIL_DOMAINS` | 允许登录的邮箱域名，逗号分隔 | 空 |
| `HAPPYIMAGE_OIDC_DEFAULT_IMAGE_QUOTA` | OIDC 新用户默认图片额度 | `0` |

OIDC 回调地址格式：

```text
<HAPPYIMAGE_API_BASE_URL>/api/auth/oidc/callback
```

生产环境跨站登录通常需要 HTTPS，并正确配置 `HAPPYIMAGE_FRONTEND_BASE_URL`、`HAPPYIMAGE_API_BASE_URL` 和 `HAPPYIMAGE_CORS_ORIGINS`。更换 `HAPPYIMAGE_SESSION_SECRET` 会让所有浏览器会话退出登录。

### 注册、代理和图库

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `HAPPYIMAGE_REGISTRATION_ENABLED` | 是否开放普通用户注册 | `false` |
| `HAPPYIMAGE_TEST_ACCOUNTS_ENABLED` | 是否启用本地测试账号 `admin/admin`、`user/user` | `false` |
| `HAPPYIMAGE_PROXY` | 上游请求代理 URL | 空 |
| `HAPPYIMAGE_PREGENERATE_THUMBNAILS_ON_START` | 启动时预生成图库缩略图 | `true` |
| `HAPPYIMAGE_THUMBNAIL_WIDTHS` | 缩略图宽度，逗号分隔 | `640` |
| `image_access_token_ttl_seconds` | 用户生成图片签名访问链接有效期，配置于 `config.json` | `86400` |

Docker 容器访问宿主机代理时可使用：

```bash
HAPPYIMAGE_PROXY=http://host.docker.internal:7897
```

### 存储后端

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `STORAGE_BACKEND` | 可选 `json`、`sqlite`、`postgres`、`git` | `json` |
| `DATABASE_URL` | SQLite / PostgreSQL 连接地址 | 空 |
| `GIT_REPO_URL` | Git 存储仓库地址 | 空 |
| `GIT_TOKEN` | Git 存储访问令牌 | 空 |
| `GIT_BRANCH` | Git 分支 | `main` |
| `GIT_FILE_PATH` | Git 仓库中的账号数据文件路径 | `accounts.json` |

PostgreSQL 示例：

```bash
STORAGE_BACKEND=postgres
DATABASE_URL=postgresql://user:password@postgres.example.com:5432/happyimage
```

SQLite 示例：

```bash
STORAGE_BACKEND=sqlite
DATABASE_URL=sqlite:///app/data/accounts.db
```

## 运行数据、图片和迁移

Docker 部署时，容器内 `/app/data` 会挂载到仓库目录下的 `./data`。本地开发时也默认使用仓库里的 `data/`。这个目录是运行数据目录，不是普通源码目录。

| 路径 | 内容 | 是否应提交到 git |
|:--|:--|:--|
| `data/images/` | 用户生成的原图，按日期分目录保存 | 否 |
| `data/image_thumbnails/` | 用户生成图片的缩略图缓存 | 否，可重新生成 |
| `data/image_index.json` | 本地图片索引和图片存储记录 | 否 |
| `data/image_tasks.json`、`data/editable_file_tasks.json` | 图片 / PPT / PSD 任务状态 | 否 |
| `data/accounts.json`、`data/auth_keys.json`、`data/accounts.db` | 号池账号、用户密钥或数据库文件 | 否，敏感 |
| `data/logs.jsonl`、`data/share_drafts.json`、`data/image_tags.json` | 日志、分享草稿、图片标签 | 否，可能敏感 |
| `data/image-gallery-seed/` | 内置官方图库种子数据 | 是，仓库已版本化 |

迁移到服务器时，至少需要迁移：

```bash
rsync -av --progress ./data/ user@server:/path/to/happyimage-api/data/
rsync -av --progress ./config.json user@server:/path/to/happyimage-api/config.json
rsync -av --progress ./.env user@server:/path/to/happyimage-api/.env
```

服务器上确认权限并重启：

```bash
ssh user@server
cd /path/to/happyimage-api
chmod 700 data
chmod 600 .env config.json
docker compose up -d
```

如果只想迁移图片历史，保留服务器已有账号和配置，只复制 `data/images/`、`data/image_thumbnails/`、`data/image_index.json`、`data/image_tags.json`。如果使用 PostgreSQL / SQLite / Git 存储账号数据，需要同时迁移对应数据库或私有 Git 存储。

> [!IMPORTANT]
> `data/` 里可能包含 OpenAI access token、refresh token、用户访问密钥、账号邮箱、密码、代理或第三方服务凭据。它不是安全的公开数据目录；当前项目不默认对这些运行数据做静态加密。请把服务器磁盘、备份文件和 Git 存储仓库都当成敏感资产管理，不要提交到公开仓库，不要发给第三方排障。

## API

外部 `/v1/*` 接口使用 Bearer token：

```bash
curl http://localhost:8000/v1/models \
  -H "Authorization: Bearer $HAPPYIMAGE_AUTH_KEY"
```

主要接口：

| 端点 | 说明 |
|:--|:--|
| `GET /v1/models` | 模型列表 |
| `POST /v1/images/generations` | 文生图 |
| `POST /v1/images/edits` | 图片编辑 |
| `POST /v1/chat/completions` | OpenAI Chat Completions 兼容入口 |
| `POST /v1/responses` | OpenAI Responses 兼容入口 |
| `POST /v1/messages` | Anthropic Messages 兼容入口 |
| `POST /v1/search` | 搜索入口 |
| `POST /v1/ppt/generations` | PPT 生成任务 |
| `POST /v1/psd/generations` | PSD 生成任务 |
| `GET /v1/editable-file-tasks` | 查询可编辑文件任务 |

Web 管理接口位于 `/api/*`，支持 Cookie 会话或 Bearer token。`/v1/*` 路由面向外部 API 客户端，建议始终使用 Bearer token。

## NewAPI 网关兼容性

HappyImage 可以作为 NewAPI 的 OpenAI-compatible 上游注册，但不是所有 Web 请求都应该经过 NewAPI。NewAPI 只适合代理模型调用；HappyImage Web 应用态接口仍应直连 HappyImage API。

完整接入方式、双向链路、同源代理配置、图片本地化和验证命令见 [NewAPI Gateway](docs/newapi-gateway.md)。本节保留核心清单，便于快速查阅。

### NewAPI 可代理接口

在 NewAPI 中按 OpenAI-compatible / 自定义 OpenAI API 渠道接入时，建议只启用以下接口：

| HappyImage 接口 | NewAPI 兼容性 | 作用 |
|:--|:--|:--|
| `GET /v1/models` | ✅ OpenAI-compatible | 返回 NewAPI 可同步的模型列表，例如 `gpt-image-2`、`auto` |
| `POST /v1/images/generations` | ✅ OpenAI-compatible | 文生图，支持 `prompt`、`model`、`n`、`size`、`quality`、`response_format` |
| `POST /v1/images/edits` | ✅ OpenAI-compatible | 图生图 / 图片编辑，支持 multipart 上传，也支持 JSON data URL |
| `POST /v1/chat/completions` | ✅ OpenAI-compatible | Chat Completions 文本与图片工作流兼容入口 |
| `POST /v1/responses` | ✅ OpenAI-compatible | Responses 文本与 `image_generation` 工具调用兼容入口 |

这些接口统一使用：

```http
Authorization: Bearer <HappyImage 用户 key 或 HAPPYIMAGE_AUTH_KEY>
```

### 不建议放入 NewAPI OpenAI 渠道的接口

| 接口 | 原因 | 应该怎么调用 |
|:--|:--|:--|
| `/api/auth/*`、`/api/settings`、`/api/accounts/*` | Web 登录、OIDC、配置和账号池管理，不是模型协议 | happyimage-web 直连 HappyImage API |
| `/api/image-tasks/*`、`/api/images/*`、`/images/*`、`/image-thumbnails/*` | 用户图库、历史任务、私有图片签名链接和下载 | happyimage-web 直连 HappyImage API |
| `/api/seed-gallery/*`、`/api/user-gallery/*`、`/api/share-drafts/*` | HappyImage 产品图库和分享草稿能力 | happyimage-web 直连 HappyImage API |
| `/api/recharge/*` | 充值会话和 NewAPI 回调适配 | 浏览器 / NewAPI 回调直连 HappyImage API |
| `POST /v1/messages` | Anthropic Messages 兼容入口，不是 OpenAI-compatible channel | 仅在 NewAPI 明确支持 Anthropic 转发时单独配置 |
| `POST /v1/search` | HappyImage 扩展搜索入口 | 自定义客户端直连 HappyImage API |
| `POST /v1/ppt/generations`、`POST /v1/psd/generations`、`GET /v1/editable-file-tasks` | HappyImage 扩展任务接口，非 OpenAI 标准 | 自定义客户端直连 HappyImage API |

### HappyImage 配置

生产环境建议设置：

```bash
HAPPYIMAGE_AUTH_KEY=replace_with_admin_or_upstream_key
HAPPYIMAGE_SESSION_SECRET=replace_with_stable_session_secret
HAPPYIMAGE_BASE_URL=https://api.example.com
HAPPYIMAGE_API_BASE_URL=https://api.example.com
HAPPYIMAGE_FRONTEND_BASE_URL=https://image.example.com
HAPPYIMAGE_CORS_ORIGINS=https://image.example.com
```

如果需要用户登录后恢复历史会话和图库，建议启用数据库存储：

```bash
STORAGE_BACKEND=postgres
DATABASE_URL=postgresql://user:password@postgres.example.com:5432/happyimage
```

`STORAGE_BACKEND=sqlite` 也可用于单机部署。数据库模式下，用户、密钥和图片任务历史会写入数据库；首次切换到数据库且 `image_tasks` 表为空时，会自动从旧的 `data/image_tasks.json` 导入图片任务历史。

如果希望 happyimage-web 图片工作台继续使用 HappyImage 的 `/api/image-tasks/*` 保存历史和图库，但底层模型调用经过 NewAPI，在 HappyImage API 上配置：

```bash
HAPPYIMAGE_MODEL_GATEWAY_BASE_URL=http://localhost:3001/v1
HAPPYIMAGE_MODEL_GATEWAY_API_KEY=sk-happyimagetest
```

这样调用链路会变成：

```text
happyimage-web /api/image-tasks/generations
  -> HappyImage API 记录任务和图库历史
  -> NewAPI /v1/images/generations
  -> HappyImage API /v1/images/generations
  -> 上游图片模型
```

### NewAPI 渠道配置

在 NewAPI 新建渠道：

| 配置项 | 值 |
|:--|:--|
| 渠道类型 | OpenAI-compatible / 自定义 OpenAI API |
| Base URL | `https://api.example.com/v1` |
| API Key | HappyImage 用户 key，或管理员 `HAPPYIMAGE_AUTH_KEY` |
| 模型 | 从 `GET /v1/models` 同步，至少包含 `gpt-image-2`、`auto` |

用 curl 验证 NewAPI 到 HappyImage 的上游链路：

```bash
curl https://<newapi-host>/v1/models \
  -H "Authorization: Bearer <NewAPI token>"

curl https://<newapi-host>/v1/images/generations \
  -H "Authorization: Bearer <NewAPI token>" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-image-2","prompt":"a small product photo on a white table","response_format":"b64_json"}'
```

### happyimage-web 配置方式

如果希望 happyimage-web 的模型调用经过 NewAPI，同时保留登录、图库、历史、充值等 HappyImage 产品能力，前端应拆成两个后端地址：

| 用途 | 地址 |
|:--|:--|
| 应用接口、登录、图库、任务历史 | `https://api.example.com` |
| OpenAI-compatible 模型调用 | `https://<newapi-host>/v1` |

也就是说，`/api/*`、`/images/*` 走 HappyImage API；`/v1/models`、`/v1/images/generations`、`/v1/images/edits`、`/v1/chat/completions`、`/v1/responses` 可以走 NewAPI。

本地开发的 happyimage-web 可使用：

```bash
BACKEND_URL=http://127.0.0.1:8000 \
MODEL_BACKEND_URL=http://127.0.0.1:3001 \
MODEL_BACKEND_API_KEY=sk-happyimagetest \
NEXT_PUBLIC_EXTERNAL_MODEL_ADMIN=true \
pnpm dev
```

其中 `MODEL_BACKEND_API_KEY` 只存在于 Next.js 服务端 middleware 环境中，用于代理 `/v1/*` 时替换为 NewAPI token，不会直接暴露给浏览器。

如果 NewAPI 已经承担号池管理、调试和上游账号设置，前端加上 `NEXT_PUBLIC_EXTERNAL_MODEL_ADMIN=true`，HappyImage Web 会隐藏本地号池和调试入口，只保留用户、图库、日志、系统设置，以及 HappyImage API 的模型网关 Base URL / token 配置。

本仓库内置了模拟 NewAPI 转发链路测试：

```bash
uv run pytest -q test/test_newapi_gateway_chain.py
```

该测试会验证 NewAPI token 到 HappyImage Bearer key 的转发、核心 OpenAI-compatible 接口响应形状，以及 `/api/*` 不属于 NewAPI 通道。

### End-to-end verification

With `happyimage-api`, `happyimage-web`, and NewAPI running:

```bash
WEB_URL=http://127.0.0.1:3000 \
API_URL=http://127.0.0.1:8000 \
HAPPYIMAGE_AUTH_KEY=<same key configured for the running happyimage-api> \
./scripts/verify-newapi-model-chain.sh
```

If `HAPPYIMAGE_AUTH_KEY` is omitted, the script falls back to `config.json`; that only works when this is the same config file used by the running `happyimage-api` service.

The script checks:

- web `/v1/models` reaches the model gateway path
- `/api/settings` redacts the model gateway token
- `/api/image-tasks/generations` creates a restorable HappyImage task

## 常用运维命令

```bash
docker compose ps
docker compose logs -f --tail=200 happyimage-api
docker compose up -d --build
curl -sf http://localhost:8000/health?format=json
```

升级前建议备份 `config.json` 和 `data/`。生产主机、远程路径、账号、密钥、代理地址和第三方令牌请放在 `.env` 或服务器私有配置中，不要提交到 git。

更多部署说明见 [Docker 部署指南](docs/docker-deployment.md)。

## 构建说明

Dockerfile 使用 China-friendly mirrors：

- Debian：`mirrors.aliyun.com`
- PyPI：`mirrors.aliyun.com/pypi/simple/`

`pyproject.toml` 也默认使用 Aliyun PyPI mirror。构建时可通过 `.env` 覆盖基础镜像：

```bash
HAPPYIMAGE_PYTHON_IMAGE=python:3.13-slim
```
