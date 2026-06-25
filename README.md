<h1 align="center">Happy Token API</h1>

<p align="center">Product-state API for Happy Token: auth, user data, image task history, private image storage, and OpenAI-compatible compatibility routes.</p>

Happy Token API 是 Happy Token 的 FastAPI 产品后端，负责登录、用户会话、图片任务历史、用户图库、私有图片访问、日志、设置和 OpenAI-compatible 兼容入口。模型账号池、上游调试、充值/额度和 GPT 逆向链路由 NewAPI 等外部模型网关管理；官方图库图片作为 Web 静态包维护，不再由 API 镜像承载。

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

- OpenAI-compatible 图片接口：`/v1/models`、`/v1/images/generations`、`/v1/images/edits`
- 图片任务接口：文生图 / 图生图任务创建、轮询、历史恢复和用户图库物化
- Web 产品接口：登录、OIDC、用户密钥、日志、设置、图片任务历史、用户图库、分享草稿
- 认证：管理员访问密钥、用户 Bearer token、OIDC 单点登录、HttpOnly Cookie 会话
- 存储：JSON、SQLite、PostgreSQL
- 部署：Docker / Docker Compose，镜像构建使用 China-friendly mirrors

## 职责边界

| 模块 | 负责 | 不负责 |
|:--|:--|:--|
| `happytoken-api`（本仓库） | 产品后端、认证会话、用户、图片任务历史、用户图库、私有图片访问、设置、日志、OpenAI-compatible 兼容入口 | 前端页面渲染、官方图库静态资源发布、NewAPI 账号池管理、充值/额度、GPT 逆向账号调试 |
| `happytoken-web` | Next.js 前端、同源 middleware、用户工作台、官方图库静态包读取、`/v1/*` 到 NewAPI 的服务端代理 | 用户历史/私有图库持久化、API 数据库、模型账号池 |
| `happytoken-gallery-source` | 官方图库源数据和候选池，供 Web 静态包导出 | 运行时服务、GitHub 版本化发布 |
| NewAPI / 模型网关 | 模型渠道、账号池、上游调试、token、额度/计费路由 | Happy Token 用户登录、历史会话、用户图库、私有图片 |

推荐链路：

```text
Browser -> happytoken-web
  /api/*, /images/*              -> happytoken-api
  /seed-gallery/*                -> happytoken-web static assets
  /v1/*                          -> NewAPI / OpenAI-compatible model gateway

happytoken-api /api/image-tasks/* -> NewAPI /v1/images/*
happytoken-api                    -> stores user, history, gallery, private image refs
```

## 仓库结构

| 路径 | 说明 |
|:--|:--|
| `api/` | FastAPI 路由和请求解析 |
| `services/` | 业务服务、协议适配、存储后端 |
| `scripts/` | 迁移、测试、部署和容器启动脚本；生产镜像仅包含 `docker-entrypoint.sh` |
| `docs/` | 部署、功能状态和产品研究文档 |
| `config.example.json` | 应用配置模板 |
| `.env.example` | Docker / 环境变量模板 |

技术架构图见 [Architecture](docs/architecture.md)。更多分层和维护约定见 [项目结构说明](docs/project-structure.md)。重大故障、根因和修复记录见 [技术日志](docs/technical-log.md)；开始新的排障 session 前建议先读该日志。

## 关联项目

| 仓库 | 说明 |
|:--|:--|
| **happytoken-api**（本仓库） | FastAPI 产品后端：API、OIDC 回调、会话、用户、历史、图库、设置 |
| [happytoken-web](https://github.com/happy-token/happytoken-web) | Next.js 前端：页面、middleware、官方图库静态包、NewAPI 同源代理 |
| `../happytoken-gallery-source`（本地/服务器目录） | 官方图库源数据和候选池，不提交 GitHub |
| [Happy Token（旧 monorepo）](https://github.com/happy-token/HappyToken) | 旧合并仓库（存档） |

当前 `docker-compose.yml` 启动的是 API 服务。前端单独由 `happytoken-web` 部署；官方图库静态包生成和发布也在 Web 项目侧处理。

## Docker 镜像

`main` 分支推送后，GitHub Actions 会构建并发布多架构 API 镜像到 GitHub Container Registry：

```bash
docker pull ghcr.io/happy-token/happytoken-api:latest
```

当前 workflow 位于 `.github/workflows/docker-publish.yml`，支持 `linux/amd64` 和 `linux/arm64`。打 `v*` tag 时会额外发布版本标签。

## 快速开始

### Docker Compose

```bash
git clone git@github.com:happy-token/happytoken-api.git
cd happytoken-api
cp .env.example .env
cp config.example.json config.json
```

编辑 `.env`，至少设置：

```bash
HAPPYTOKEN_SESSION_SECRET=generate-a-random-secret-at-least-32-chars
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
git clone git@github.com:happy-token/happytoken-api.git
cd happytoken-api
cp config.example.json config.json
export HAPPYTOKEN_SESSION_SECRET=generate-a-random-secret-at-least-32-chars
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
| `HAPPYTOKEN_SESSION_SECRET` | Web 登录会话签名密钥，建议至少 32 字符，生产环境必须稳定保存 |

### 服务地址与 CORS

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `HAPPYTOKEN_BASE_URL` | 对外基础 URL，影响图片绝对地址 | 空 |
| `HAPPYTOKEN_FRONTEND_BASE_URL` | 前端公开地址，OIDC 登录后重定向目标 | 空 |
| `HAPPYTOKEN_API_BASE_URL` | 后端公开地址，用于构造 OIDC 回调 URL | `HAPPYTOKEN_BASE_URL` |
| `HAPPYTOKEN_CORS_ORIGINS` | 允许的跨域来源，逗号分隔 | `HAPPYTOKEN_FRONTEND_BASE_URL` |

图片生成不再使用后端 `.env` 中的模型网关变量兜底。普通用户登录后会自动获得默认 HappyToken 供应商；用户也可以在 Web 的“我的 -> 供应商”中添加其他 OpenAI-compatible 供应商或自定义供应商。后端只使用当前用户选中的供应商发起文生图 / 图生图请求。

### 会话与 OIDC

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `HAPPYTOKEN_SESSION_SECRET` | 会话签名密钥，Web 登录和 OIDC 登录必需 | 空 |
| `HAPPYTOKEN_SESSION_COOKIE_NAME` | 会话 Cookie 名称 | `happytoken_session` |
| `HAPPYTOKEN_SESSION_MAX_AGE_SECONDS` | 会话过期时间（秒） | `86400` |
| `HAPPYTOKEN_OIDC_ENABLED` | 是否启用 OIDC | `false` |
| `HAPPYTOKEN_OIDC_ISSUER` | OIDC issuer URL | 空 |
| `HAPPYTOKEN_OIDC_CLIENT_ID` | OAuth Client ID | 空 |
| `HAPPYTOKEN_OIDC_CLIENT_SECRET` | OAuth Client Secret | 空 |
| `HAPPYTOKEN_OIDC_SCOPES` | OIDC scopes | `openid profile email` |
| `HAPPYTOKEN_OIDC_ALLOWED_EMAIL_DOMAINS` | 允许登录的邮箱域名，逗号分隔 | 空 |

OIDC 回调地址格式：

```text
<HAPPYTOKEN_API_BASE_URL>/api/auth/oidc/callback
```

生产环境跨站登录通常需要 HTTPS，并正确配置 `HAPPYTOKEN_FRONTEND_BASE_URL`、`HAPPYTOKEN_API_BASE_URL` 和 `HAPPYTOKEN_CORS_ORIGINS`。更换 `HAPPYTOKEN_SESSION_SECRET` 会让所有浏览器会话退出登录。

### 注册

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `HAPPYTOKEN_REGISTRATION_ENABLED` | 是否开放普通用户注册 | `false` |
| `image_access_token_ttl_seconds` | 用户生成图片签名访问链接有效期，配置于 `config.json` | `86400` |

### 存储后端

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `STORAGE_BACKEND` | 存储后端，生产环境推荐 `postgres` | `json` |
| `DATABASE_URL` | PostgreSQL 连接地址；`STORAGE_BACKEND=postgres` 时必填 | 空 |

PostgreSQL 示例：

```bash
STORAGE_BACKEND=postgres
DATABASE_URL=postgresql://user:password@postgres.example.com:5432/happytoken
```

SQLite 示例：
SQLite 仅用于临时本地开发和自动化测试，不建议生产部署使用。

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
| `../happytoken-gallery-source/image-gallery-seed/` | 官方图库源数据 | 仓库外保存；生产使用 web 静态包 |

迁移到服务器时，至少需要迁移：

```bash
rsync -av --progress ./data/ user@server:/path/to/happytoken-api/data/
rsync -av --progress ./config.json user@server:/path/to/happytoken-api/config.json
rsync -av --progress ./.env user@server:/path/to/happytoken-api/.env
```

服务器上确认权限并重启：

```bash
ssh user@server
cd /path/to/happytoken-api
chmod 700 data
chmod 600 .env config.json
docker compose up -d
```

如果只想迁移图片历史，保留服务器已有配置，只复制 `data/images/`、`data/image_thumbnails/`、`data/image_index.json`、`data/image_tags.json`。如果使用 PostgreSQL / SQLite 存储用户数据，需要同时迁移对应数据库。官方图库请在 `happytoken-web` 中通过 `pnpm run gallery:build` 生成静态包，或部署时挂载到 Web 容器。

> [!IMPORTANT]
> `data/` 里可能包含 OpenAI access token、refresh token、用户访问密钥、账号邮箱、密码、代理或第三方服务凭据。它不是安全的公开数据目录；当前项目不默认对这些运行数据做静态加密。请把服务器磁盘、备份文件和 Git 存储仓库都当成敏感资产管理，不要提交到公开仓库，不要发给第三方排障。

## API

外部 `/v1/*` 接口使用 Bearer token：

```bash
curl http://localhost:8000/v1/models \
  -H "Authorization: Bearer $HAPPYTOKEN_USER_TOKEN"
```

主要接口：

| 端点 | 说明 |
|:--|:--|
| `GET /v1/models` | 模型列表 |
| `POST /v1/images/generations` | 文生图 |
| `POST /v1/images/edits` | 图片编辑 |

Web 管理接口位于 `/api/*`，支持 Cookie 会话或 Bearer token。`/v1/*` 路由面向外部 API 客户端，建议始终使用 Bearer token。

### 图片生成类型与接口

Happy Token 同时提供两组图片接口：一组是产品工作台使用的任务接口，负责历史 session、用户图库、私有图片签名和下载管理；另一组是外部 OpenAI-compatible 接口，供 NewAPI、Cherry Studio 或自定义客户端调用。

| 生图类型 | 什么时候使用 | 产品任务接口 | 外部 OpenAI-compatible 接口 |
|:--|:--|:--|:--|
| 文生图 | 只有提示词，没有参考图、源图或人物身份参考 | `POST /api/image-tasks/generations` | `POST /v1/images/generations` |
| 图生图 / 图片编辑 | 上传一张或多张图片作为参考图，或提示词要求“参考这张图 / 保持人脸 / 使用上传图片” | `POST /api/image-tasks/edits` | `POST /v1/images/edits` |

工作台、浏览器页面和需要恢复历史记录的客户端应使用 `/api/image-tasks/*`。这些接口会创建可轮询任务，并把成功结果物化到 Happy Token 图片存储。

文生图任务示例：

```bash
curl http://localhost:8000/api/image-tasks/generations \
  -H "Authorization: Bearer $HAPPYTOKEN_USER_TOKEN" \
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
  -H "Authorization: Bearer $HAPPYTOKEN_USER_TOKEN" \
  -F client_task_id=demo-edit-001 \
  -F model=gpt-image-2 \
  -F prompt="change the background to a clean studio scene" \
  -F size=1024x1024 \
  -F quality=auto \
  -F image=@./reference.png
```

外部 OpenAI-compatible 文生图示例：

```bash
curl http://localhost:8000/v1/images/generations \
  -H "Authorization: Bearer $HAPPYTOKEN_USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "a small product photo on a white table",
    "size": "1024x1024",
    "quality": "auto",
    "response_format": "b64_json"
  }'
```

外部 OpenAI-compatible 图生图 / 图片编辑示例：

```bash
curl http://localhost:8000/v1/images/edits \
  -H "Authorization: Bearer $HAPPYTOKEN_USER_TOKEN" \
  -F model=gpt-image-2 \
  -F prompt="change the background to a clean studio scene" \
  -F size=1024x1024 \
  -F quality=auto \
  -F image=@./reference.png
```

如果提示词明确要求参考图、上传图、人脸身份保持或源图，但请求没有上传图片，应该使用图生图接口并附带 `image`。纯文生图接口不会自动补充参考图。

### 图片生成错误提示

Happy Token API 不再管理本地 image quota，也不会从 `.env` 读取模型网关密钥作为普通用户兜底。图片生成只使用当前用户在 Web“我的 -> 供应商”中选中的 Base URL 和 API Key。默认 HappyToken 供应商由登录绑定流程生成，充值、余额、额度和计费由 NewAPI 或外部模型供应商负责。

后端会把常见上游错误转换为可直接展示给用户的中文提示：

| 场景 | 用户提示 |
|:--|:--|
| 用户没有配置供应商 | 请先在用户设置中配置模型供应商 Base URL 和 API Key。 |
| 上游返回 quota / credit / balance / billing / 余额 / 额度不足 | 模型供应商额度不足，请先充值或更换供应商后再试。 |
| 上游返回 401、invalid api key、invalid token | 模型供应商 API Key 无效或已过期，请在用户设置里更新 API Key。 |
| 上游连接中断、curl TLS、OpenSSL、connection reset | 连接模型供应商失败，请稍后重试；如果持续出现，请检查 Base URL 或网络代理。 |
| 模型不存在或不可用 | 当前模型不可用，请在生图页面切换可用模型后再试。 |

这些错误会写入图片任务历史，前端轮询历史任务时也会显示相同的友好提示。

## NewAPI 网关兼容性

Happy Token 可以作为 NewAPI 的 OpenAI-compatible 上游注册，但不是所有 Web 请求都应该经过 NewAPI。NewAPI 只适合代理模型调用；Happy Token Web 应用态接口仍应直连 Happy Token API。

完整接入方式、双向链路、同源代理配置、图片本地化和验证命令见 [NewAPI Gateway](docs/newapi-gateway.md)。本节保留核心清单，便于快速查阅。

### NewAPI 可代理接口

在 NewAPI 中按 OpenAI-compatible / 自定义 OpenAI API 渠道接入时，建议只启用以下接口：

| Happy Token 接口 | NewAPI 兼容性 | 作用 |
|:--|:--|:--|
| `GET /v1/models` | ✅ OpenAI-compatible | 返回 NewAPI 可同步的模型列表，例如 `gpt-image-2`、`auto` |
| `POST /v1/images/generations` | ✅ OpenAI-compatible | 文生图，支持 `prompt`、`model`、`n`、`size`、`quality`、`response_format` |
| `POST /v1/images/edits` | ✅ OpenAI-compatible | 图生图 / 图片编辑，支持 multipart 上传，也支持 JSON data URL |

这些接口统一使用：

```http
Authorization: Bearer <Happy Token 用户 token>
```

### 不建议放入 NewAPI OpenAI 渠道的接口

| 接口 | 原因 | 应该怎么调用 |
|:--|:--|:--|
| `/api/auth/*`、`/api/settings` | Web 登录、OIDC、用户和系统配置，不是模型协议 | happytoken-web 直连 Happy Token API |
| `/api/image-tasks/*`、`/api/images/*`、`/images/*`、`/image-thumbnails/*` | 用户图库、历史任务、私有图片签名链接和下载 | happytoken-web 直连 Happy Token API |
| `/api/seed-gallery/*`、`/api/user-gallery/*`、`/api/share-drafts/*` | 用户图库和分享草稿属于产品接口；`/api/seed-gallery/*` 仅作为旧兼容 fallback，正式官方图库由 Web 静态包提供 | happytoken-web 直连 Happy Token API；官方图库优先读 `/seed-gallery/*` |

### Happy Token 配置

生产环境建议设置：

```bash
HAPPYTOKEN_SESSION_SECRET=replace_with_stable_session_secret
HAPPYTOKEN_BASE_URL=https://api.example.com
HAPPYTOKEN_API_BASE_URL=https://api.example.com
HAPPYTOKEN_FRONTEND_BASE_URL=https://image.example.com
HAPPYTOKEN_CORS_ORIGINS=https://image.example.com
```

如果需要用户登录后恢复历史会话和图库，建议启用数据库存储：

```bash
STORAGE_BACKEND=postgres
DATABASE_URL=postgresql://user:password@postgres.example.com:5432/happytoken
```

`STORAGE_BACKEND=sqlite` 也可用于单机部署。数据库模式下，用户、密钥和图片任务历史会写入数据库；首次切换到数据库且 `image_tasks` 表为空时，会自动从旧的 `data/image_tasks.json` 导入图片任务历史。

如果希望 happytoken-web 图片工作台继续使用 Happy Token 的 `/api/image-tasks/*` 保存历史和图库，但底层模型调用经过 NewAPI，请让用户在 Web 的“我的 -> 供应商”中添加 NewAPI 供应商：

| 字段 | 示例 |
|:--|:--|
| 供应商类型 | `newapi` |
| Base URL | `http://localhost:3001/v1` |
| API Key | NewAPI token |

这样调用链路会变成：

```text
happytoken-web /api/image-tasks/generations
  -> Happy Token API 记录任务和图库历史
  -> NewAPI /v1/images/generations
  -> Happy Token API /v1/images/generations
  -> 上游图片模型
```

### NewAPI 渠道配置

在 NewAPI 新建渠道：

| 配置项 | 值 |
|:--|:--|
| 渠道类型 | OpenAI-compatible / 自定义 OpenAI API |
| Base URL | `https://api.example.com/v1` |
| API Key | Happy Token 用户 token |
| 模型 | 从 `GET /v1/models` 同步，至少包含 `gpt-image-2`、`auto` |

用 curl 验证 NewAPI 到 Happy Token 的上游链路：

```bash
curl https://<newapi-host>/v1/models \
  -H "Authorization: Bearer <NewAPI token>"

curl https://<newapi-host>/v1/images/generations \
  -H "Authorization: Bearer <NewAPI token>" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-image-2","prompt":"a small product photo on a white table","response_format":"b64_json"}'
```

### happytoken-web 配置方式

如果希望 happytoken-web 的模型调用经过 NewAPI，同时保留登录、图库、历史等 Happy Token 产品能力，前端应拆成两个后端地址：

| 用途 | 地址 |
|:--|:--|
| 应用接口、登录、图库、任务历史 | `https://api.example.com` |
| OpenAI-compatible 模型调用 | `https://<newapi-host>/v1` |

也就是说，`/api/*`、`/images/*` 走 Happy Token API；`/v1/models`、`/v1/images/generations`、`/v1/images/edits` 可以走 NewAPI。

本地开发的 happytoken-web 可使用：

```bash
BACKEND_URL=http://127.0.0.1:8000 \
MODEL_BACKEND_URL=http://127.0.0.1:3001 \
MODEL_BACKEND_API_KEY=sk-happytokentest \
NEXT_PUBLIC_EXTERNAL_MODEL_ADMIN=true \
pnpm dev
```

其中 `MODEL_BACKEND_API_KEY` 只存在于 Next.js 服务端 middleware 环境中，用于代理 `/v1/*` 时替换为 NewAPI token，不会直接暴露给浏览器。

如果 NewAPI 已经承担号池管理、调试和上游账号设置，前端加上 `NEXT_PUBLIC_EXTERNAL_MODEL_ADMIN=true`，Happy Token Web 会隐藏本地号池和调试入口，只保留用户、用户图库、日志、系统设置，以及普通用户自己的供应商配置。

本仓库内置了模拟 NewAPI 转发链路测试：

```bash
uv run pytest -q test/test_newapi_gateway_chain.py
```

该测试会验证 NewAPI token 到 Happy Token Bearer key 的转发、核心 OpenAI-compatible 接口响应形状，以及 `/api/*` 不属于 NewAPI 通道。

### End-to-end verification

With `happytoken-api`, `happytoken-web`, and NewAPI running:

```bash
WEB_URL=http://127.0.0.1:3000 \
API_URL=http://127.0.0.1:8000 \
HAPPYTOKEN_USER_TOKEN=<Happy Token user token> \
./scripts/verify-newapi-model-chain.sh
```

`HAPPYTOKEN_USER_TOKEN` should be the token for the Happy Token user selected as the upstream account.

The script checks:

- web `/v1/models` reaches the model gateway path
- `/api/settings` remains a product settings route and does not provide the user's provider API Key
- `/api/image-tasks/generations` creates a restorable Happy Token task

图片链路回归测试建议同时运行：

```bash
uv run python -m pytest -q test/test_model_gateway_service.py test/test_image_tasks_api.py test/test_image_task_service.py test/test_cookie_session_auth.py test/test_newapi_gateway_chain.py
```

该测试覆盖用户供应商配置、文生图任务、图生图 / 图片编辑任务、任务恢复、NewAPI 图片链路和上游错误提示转换。

## 常用运维命令

```bash
docker compose ps
docker compose logs -f --tail=200 happytoken-api
docker compose up -d --build
curl -sf http://localhost:8000/health?format=json
```

升级前建议备份 `config.json` 和 `data/`。生产主机、远程路径、密钥和第三方令牌请放在 `.env` 或服务器私有配置中，不要提交到 git。

更多部署说明见 [Docker 部署指南](docs/docker-deployment.md)。

## 构建说明

Dockerfile 使用 China-friendly mirrors：

- Debian：`mirrors.aliyun.com`
- PyPI：`mirrors.aliyun.com/pypi/simple/`

`pyproject.toml` 也默认使用 Aliyun PyPI mirror。构建时可通过 `.env` 覆盖基础镜像：

```bash
HAPPYTOKEN_PYTHON_IMAGE=python:3.13-slim
```

## Unified Login / NewAPI Binding

Normal users should authenticate through Casdoor OIDC. Public password login is disabled unless `HAPPYTOKEN_LOCAL_PASSWORD_LOGIN_ENABLED=true` is set for emergency operations.

NewAPI binding environment:

```bash
HAPPYTOKEN_NEWAPI_BASE_URL=https://gateway.happy-token.cn
HAPPYTOKEN_NEWAPI_MANAGEMENT_URL=https://gateway.happy-token.cn
HAPPYTOKEN_NEWAPI_PROVISION_URL=http://newapi:3000/api/internal/happyimage/bind-token
HAPPYTOKEN_NEWAPI_PROVISION_SECRET=replace-with-internal-secret
HAPPYTOKEN_NEWAPI_TOKEN_NAME="HappyImage Default"
```

Direct SQL provisioning is also supported:

```bash
HAPPYTOKEN_NEWAPI_SQL_DSN=postgresql://newapi_user:newapi_pass@newapi-postgres:5432/newapi
```

If neither a complete provisioning endpoint configuration nor `HAPPYTOKEN_NEWAPI_SQL_DSN` is available, OIDC login still succeeds and the user session reports `newapi_binding_status=pending`.

`HAPPYIMAGE_NEWAPI_*` environment variable names are accepted as legacy fallbacks, but new deployments should use `HAPPYTOKEN_NEWAPI_*`.

Binding behavior:

- OIDC callback creates or reuses the local Happy Token user, then tries to create or reuse the NewAPI user/token.
- `/api/auth/session` retries binding when the current user has OIDC identity but the stored HappyToken provider is still pending or failed.
- `/api/auth/newapi-management` is the authenticated product endpoint used by `/settings/newapi`; it returns binding status, NewAPI user ID, token list, default API Key and the external management URL.
- When binding status is `configured`, stale frontend messages such as `NewAPI SQL provisioning request failed` should be ignored and cleared.

If the current status is truly `failed`, login still works, but the default HappyToken provider may not have a usable API Key. In that state image generation through HappyToken can fail until SQL/provisioning is fixed or the user selects another provider. SQL failures are logged as `newapi_sql_provisioning_failed` with the error type/message and a redacted DSN so operators can distinguish database connectivity, schema, and permission problems.

`/settings/newapi` deliberately does not rely on NewAPI iframe auto-login. Provisioning creates database users and tokens, not a browser `session` cookie for `gateway.happy-token.cn`; the gateway admin UI can therefore show “not logged in” even when the HappyImage binding is healthy.
