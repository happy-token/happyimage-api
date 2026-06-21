# Docker 部署指南

本文说明 HappyImage API 使用 Docker Compose 启动、升级和排障的常用流程。生产主机、远程路径、账号、密钥、代理地址和第三方令牌请放在 `.env` 或服务器私有配置中，不要提交到 git。

## 当前部署形态

当前仓库的 `docker-compose.yml` 只启动后端 API 服务：

| 服务 | 容器名 | 默认端口 | 说明 |
|:--|:--|:--|:--|
| `happyimage-api` | `happyimage-api` | `8000` | FastAPI 后端，提供 OpenAI-compatible API、OIDC 回调、会话管理、账号池和 Web 管理接口 |

前端项目位于 [happyimage-web](https://github.com/happy-token/happyimage-web)，可单独部署。后端代码仍保留静态资源托管能力：如果镜像或运行目录中存在前端构建产物，后端会尝试直接返回 Web 页面；否则只提供 API。

当前 `happyimage-web` Docker 镜像运行 Next.js server，而不是静态 nginx。这样生产 Docker 部署也能使用 Web middleware 将 `/api/*`、`/images/*` 转发到 HappyImage API，并将 `/v1/*` 转发到 NewAPI。

## 文件说明

| 文件 | 用途 |
|:--|:--|
| `docker-compose.yml` | 默认 API 服务配置，宿主机端口 `8000` 映射到容器 `80` |
| `.env.example` | 环境变量模板，复制为 `.env` 后填写本机或服务器配置 |
| `config.example.json` | 应用配置模板，复制为 `config.json` 后可在设置页继续维护 |
| `data/` | 运行数据目录，包含账号、日志、图片任务、缓存图片和图库种子数据 |
| `scripts/docker-entrypoint.sh` | 容器启动入口，负责初始化图库种子数据和可选缩略图预生成 |

## 首次启动

```bash
cp .env.example .env
cp config.example.json config.json
```

编辑 `.env`，至少设置：

```bash
HAPPYIMAGE_AUTH_KEY=replace_with_a_strong_secret
HAPPYIMAGE_SESSION_SECRET=generate-a-random-secret-at-least-32-chars
```

启动服务：

```bash
docker compose up -d --build
docker compose ps
curl -sf http://localhost:8000/health?format=json
```

默认访问地址：

| 服务 | 地址 |
|:--|:--|
| API 根地址 | `http://localhost:8000` |
| OpenAI-compatible base URL | `http://localhost:8000/v1` |
| 健康检查 | `http://localhost:8000/health?format=json` |

## 预构建镜像

`main` 分支推送后，GitHub Actions 会把 API 镜像发布到 GitHub Container Registry：

```bash
docker pull ghcr.io/happy-token/happyimage-api:latest
```

镜像支持 `linux/amd64` 和 `linux/arm64`。当前默认 `docker-compose.yml` 仍使用本地构建，生产环境如果想直接使用预构建镜像，可以把服务中的 `build` 段移除并设置：

```yaml
image: ghcr.io/happy-token/happyimage-api:latest
```

## 配置 OIDC 单点登录

1. 在 OIDC 提供方（如 Google、Azure AD、Keycloak）创建 OAuth 应用，获取 Client ID 和 Client Secret。
2. 设置回调地址：`<HAPPYIMAGE_API_BASE_URL>/api/auth/oidc/callback`，例如 `https://api.example.com/api/auth/oidc/callback`。
3. 在 `.env` 中配置：

```bash
HAPPYIMAGE_SESSION_SECRET=generate-a-random-secret-at-least-32-chars
HAPPYIMAGE_OIDC_ENABLED=true
HAPPYIMAGE_OIDC_ISSUER=https://accounts.google.com
HAPPYIMAGE_OIDC_CLIENT_ID=your-client-id.apps.googleusercontent.com
HAPPYIMAGE_OIDC_CLIENT_SECRET=your-client-secret
HAPPYIMAGE_API_BASE_URL=https://api.example.com
HAPPYIMAGE_FRONTEND_BASE_URL=https://image.example.com
HAPPYIMAGE_CORS_ORIGINS=https://image.example.com

# 可选
HAPPYIMAGE_OIDC_ALLOWED_EMAIL_DOMAINS=example.com
HAPPYIMAGE_OIDC_DEFAULT_IMAGE_QUOTA=10
```

4. 重启服务：

```bash
docker compose up -d happyimage-api
```

生产环境注意事项：

- 生产环境跨站登录通常需要 HTTPS，否则浏览器可能拒绝跨站 Cookie。
- `HAPPYIMAGE_SESSION_SECRET` 必须是稳定随机字符串，更换后所有用户会退出登录。
- `HAPPYIMAGE_CORS_ORIGINS` 必须包含前端公开地址。
- 管理员访问密钥登录不受 OIDC 配置影响；OIDC 配错时可用 `HAPPYIMAGE_AUTH_KEY` 恢复登录。

## 配置 NewAPI 模型网关

如果号池管理、模型调试和上游账号设置已经迁移到 NewAPI，HappyImage API 可以只负责登录、图库、历史会话、私有图片和任务状态，底层模型请求走 NewAPI：

```bash
HAPPYIMAGE_MODEL_GATEWAY_BASE_URL=https://newapi.example.com/v1
HAPPYIMAGE_MODEL_GATEWAY_API_KEY=<newapi-token>
HAPPYIMAGE_REQUIRE_MODEL_GATEWAY=true
```

`docker-compose.yml` 和 `docker-compose.local.yml` 会把这些变量透传给容器。`HAPPYIMAGE_REQUIRE_MODEL_GATEWAY=true` 会在网关缺失时让 `/api/image-tasks/*` 明确失败，避免意外回退到本地号池。

前端 `happyimage-web` 推荐使用同源代理：

```bash
BACKEND_URL=https://api.example.com
MODEL_BACKEND_URL=https://newapi.example.com/v1
MODEL_BACKEND_API_KEY=<newapi-token>
NEXT_PUBLIC_EXTERNAL_MODEL_ADMIN=true
```

同源代理模式下不要设置 `NEXT_PUBLIC_API_BASE_URL`。让浏览器请求保持为 `/api/*`、`/images/*`、`/v1/*`，由 Web middleware 根据路径转发。完整说明见 [NewAPI Gateway](newapi-gateway.md)。

Web Docker 运行示例：

```bash
docker run -p 3000:3000 \
  -v /srv/happyimage/seed-gallery:/app/web/public/seed-gallery:ro \
  -e BACKEND_URL=https://api.example.com \
  -e MODEL_BACKEND_URL=https://newapi.example.com/v1 \
  -e MODEL_BACKEND_API_KEY=<newapi-token> \
  happyimage-web
```

官方图库是 web 静态包，不再内置到 API 镜像。生成或更新静态包：

```bash
uv run python scripts/pregenerate_seed_gallery_thumbnails.py \
  --seed-dir ~/workspace/HappyImage/happyimage-gallery-source/image-gallery-seed \
  --candidate-dir ~/workspace/HappyImage/happyimage-gallery-source/image-gallery-candidates \
  --widths 640 \
  --quiet

uv run python scripts/export_seed_gallery_static.py \
  --seed-dir ~/workspace/HappyImage/happyimage-gallery-source/image-gallery-seed \
  --candidate-dir ~/workspace/HappyImage/happyimage-gallery-source/image-gallery-candidates \
  --output /srv/happyimage/seed-gallery \
  --copy-assets
```

`/srv/happyimage/seed-gallery` 应包含 `static/items.json`、`images/` 和 `thumbnails/w640/`。该目录可能很大，建议放在服务器磁盘、对象存储或 CDN，不要提交到 GitHub。

## 配置优先级

`HAPPYIMAGE_AUTH_KEY`、`HAPPYIMAGE_BASE_URL`、OIDC、会话和模型网关相关环境变量会覆盖 `config.json` 中的对应值。推荐把密钥、模型网关 token 和部署域名放在 `.env`，把功能开关和运行参数放在 `config.json` 或 Web 设置页。

OIDC 配置在 Web 设置页修改后，Client Secret 会脱敏显示。保存时如果留空 Client Secret，会保留旧值；填入新值则替换。

## 环境变量参考

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
| `HAPPYIMAGE_MODEL_GATEWAY_BASE_URL` | OpenAI-compatible 模型网关地址，例如 NewAPI `/v1` | 空 |
| `HAPPYIMAGE_MODEL_GATEWAY_API_KEY` | 模型网关 API Key，例如 NewAPI token | 空 |
| `HAPPYIMAGE_REQUIRE_MODEL_GATEWAY` | 是否要求图片任务必须走模型网关 | `false` |

### 会话

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `HAPPYIMAGE_SESSION_SECRET` | 会话签名密钥，Web 登录和 OIDC 登录必需 | 空 |
| `HAPPYIMAGE_SESSION_COOKIE_NAME` | 会话 Cookie 名称 | `happyimage_session` |
| `HAPPYIMAGE_SESSION_MAX_AGE_SECONDS` | 会话过期时间（秒） | `86400` |

### OIDC

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `HAPPYIMAGE_OIDC_ENABLED` | 是否启用 OIDC 登录 | `false` |
| `HAPPYIMAGE_OIDC_ISSUER` | OIDC 提供方 issuer URL | 空 |
| `HAPPYIMAGE_OIDC_CLIENT_ID` | OAuth Client ID | 空 |
| `HAPPYIMAGE_OIDC_CLIENT_SECRET` | OAuth Client Secret | 空 |
| `HAPPYIMAGE_OIDC_SCOPES` | 请求的 scope | `openid profile email` |
| `HAPPYIMAGE_OIDC_ALLOWED_EMAIL_DOMAINS` | 允许的邮箱域名，逗号分隔，留空不限制 | 空 |
| `HAPPYIMAGE_OIDC_DEFAULT_IMAGE_QUOTA` | OIDC 新用户默认图片额度 | `0` |

### 注册

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `HAPPYIMAGE_REGISTRATION_ENABLED` | 是否开放普通用户注册 | `false` |
| `image_access_token_ttl_seconds` | 用户生成图片签名访问链接有效期，配置于 `config.json` | `86400` |

### 存储

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `STORAGE_BACKEND` | 存储后端，可选 `json`、`sqlite`、`postgres` | `json` |
| `DATABASE_URL` | SQLite 或 PostgreSQL 连接地址 | 空 |

## 存储后端

默认 `docker-compose.yml` 使用 `json` 存储，数据保存在 `./data`。

SQLite 示例：

```bash
STORAGE_BACKEND=sqlite
DATABASE_URL=sqlite:///app/data/accounts.db
```

PostgreSQL 示例：

```bash
STORAGE_BACKEND=postgres
DATABASE_URL=postgresql://user:password@postgres.example.com:5432/happyimage
```

## 运行数据与服务器迁移

默认 Docker Compose 会把宿主机 `./data` 挂载到容器 `/app/data`，把 `./config.json` 挂载到容器 `/app/config.json`。因此本地图片和运行状态主要在宿主机当前仓库的 `data/` 下。

常见数据位置：

| 路径 | 内容 | 迁移建议 |
|:--|:--|:--|
| `data/images/` | 用户生成原图 | 需要保留历史图片时迁移 |
| `data/image_thumbnails/` | 缩略图缓存 | 可迁移，也可服务器重新生成 |
| `data/image_index.json` | 图片索引 | 迁移图片时一起迁移 |
| `data/image_tasks.json`、`data/editable_file_tasks.json` | 图片 / PPT / PSD 任务状态 | 需要保留任务历史时迁移 |
| `data/auth_keys.json`、`data/accounts.db` | 用户密钥、用户数据或 SQLite 数据库 | 敏感，按生产数据迁移 |
| `data/logs.jsonl`、`data/share_drafts.json`、`data/image_tags.json` | 日志、分享草稿、图片标签 | 需要保留后台数据时迁移 |
| `../happyimage-gallery-source/image-gallery-seed/` | 官方图库源数据 | 仓库外保存，用于导出 web 静态包；生产不需要挂载到 API 容器 |

完整迁移示例：

```bash
rsync -av --progress ./data/ user@server:/srv/happyimage-api/data/
rsync -av --progress ./config.json user@server:/srv/happyimage-api/config.json
rsync -av --progress ./.env user@server:/srv/happyimage-api/.env

ssh user@server
cd /srv/happyimage-api
chmod 700 data
chmod 600 .env config.json
docker compose up -d
```

只迁移图片历史时，复制 `data/images/`、`data/image_thumbnails/`、`data/image_index.json` 和 `data/image_tags.json` 即可；不要覆盖服务器已有的 `auth_keys.json` 或数据库，除非你明确要迁移用户、密钥和历史任务数据。

安全注意：

- `data/` 不是公开资源目录，里面可能包含用户访问密钥、邮箱、日志、图片、数据库或第三方服务凭据。
- 当前项目默认不对 `data/` 做静态加密。安全性依赖服务器文件权限、磁盘加密、备份加密和仓库访问控制。
- `.gitignore` 默认忽略 `data/*`。不要把 `data/auth_keys.json`、数据库文件、日志、备份或生成后的官方图库静态包提交到公开仓库。

## 构建代理配置

如果 Docker Desktop 构建阶段没有继承系统代理，可以只给本次构建设置 HTTP 代理：

```bash
HTTP_PROXY=http://127.0.0.1:7897 \
HTTPS_PROXY=http://127.0.0.1:7897 \
docker compose up -d --build
```

## 升级

```bash
git pull
docker compose build happyimage-api
docker compose up -d happyimage-api
docker compose ps
curl -sf http://localhost:8000/health?format=json
```

升级前建议备份 `config.json` 和 `data/`。如果使用外部 PostgreSQL，也要按数据库备份流程单独备份。

## 日志和排障

查看服务状态：

```bash
docker compose ps
```

查看服务日志：

```bash
docker compose logs -f --tail=200 happyimage-api
```

重新构建：

```bash
docker compose build --no-cache happyimage-api
docker compose up -d happyimage-api
```

如果 Docker Desktop 报本地镜像 blob `input/output error`，通常是 Docker 本地镜像存储损坏。可以先尝试删除本项目镜像并重建：

```bash
docker image rm happyimage-api:latest
docker compose build --no-cache
docker compose up -d
```

如果连 `docker image ls` 都报同类错误，需要重启 Docker Desktop；仍无法恢复时，再考虑清理 Docker Desktop 的构建缓存或重置本地镜像数据。

## 常见问题

**OIDC 登录后会话立即失效**

检查：

- `HAPPYIMAGE_SESSION_SECRET` 是否已设置
- `HAPPYIMAGE_FRONTEND_BASE_URL` 和 `HAPPYIMAGE_API_BASE_URL` 是否正确
- 生产环境是否使用 HTTPS
- `HAPPYIMAGE_CORS_ORIGINS` 是否包含前端地址

**OIDC 回调返回 state 不匹配**

通常是用户在浏览器中打开了多次授权页面。重新点击登录按钮即可。

**管理员无法登录**

管理员本地密码 / 访问密钥登录不受 OIDC 配置影响。使用 `HAPPYIMAGE_AUTH_KEY` 作为访问密钥即可登录修复配置。
