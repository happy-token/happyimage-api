# Docker 部署指南

本文说明 HappyImage API 使用 Docker Compose 启动、升级和排障的常用流程。生产主机、远程路径、账号、密钥、代理地址和第三方令牌不要提交到 git；基础设施覆盖才放 `.env`，应用运行时设置放 `config.json`、首次 `/setup` 或 Web 管理设置页。

## 当前部署形态

当前仓库的 `docker-compose.yml` 只启动后端 API 服务：

| 服务 | 容器名 | 默认端口 | 说明 |
|:--|:--|:--|:--|
| `happyimage-api` | `happytoken-api` | `8000` | FastAPI 后端，提供 OIDC 回调、会话管理、用户图库、图片任务历史和 Web 管理接口 |

前端项目位于 `happyimage-web`，可单独部署。Web middleware 只将 `/api/*`、`/images/*`、`/image-thumbnails/*` 和 `/health` 转发到 `BACKEND_URL`；Web 不再代理外部 model API 路径。

## 文件说明

| 文件 | 用途 |
|:--|:--|
| `docker-compose.yml` | 默认 API 服务配置，宿主机端口 `8000` 映射到容器 `80` |
| `.env.example` | 可选基础设施环境变量模板；只有要覆盖端口、镜像、存储后端或数据库连接时才复制为 `.env` |
| `config.example.json` | 应用运行时配置模板，复制为 `config.json` 后由首次 `/setup` 或设置页继续维护 |
| `data/` | 运行数据目录，包含用户、日志、图片任务和缓存图片 |
| `scripts/docker-entrypoint.sh` | 容器启动入口，负责初始化运行数据目录 |

## 首次启动

```bash
cp config.example.json config.json
docker compose up -d
docker compose ps
curl -sf http://localhost:8000/health?format=json
```

默认访问地址：

| 服务 | 地址 |
|:--|:--|
| API 根地址 | `http://localhost:8000` |
| 健康检查 | `http://localhost:8000/health?format=json` |

默认启动不需要 `.env`。只有要覆盖端口、镜像、存储后端或 `DATABASE_URL` 时，才复制 `.env.example` 为 `.env`。首次部署后，使用 Web `/setup` 或管理设置页维护公开地址、会话密钥、OIDC、NewAPI 绑定、模型网关、图片存储、代理和安全设置。

## 预构建镜像

`main` 分支推送后，GitHub Actions 会把 API 镜像发布到 GitHub Container Registry：

```bash
docker pull ghcr.io/happy-token/happyimage-api:latest
```

镜像支持 `linux/amd64` 和 `linux/arm64`。当前默认 `docker-compose.yml` 使用：

```yaml
image: ghcr.io/happy-token/happyimage-api:latest
```

## 配置优先级

配置分两层：

| 层级 | 文件 / 入口 | 放什么 |
|:--|:--|:--|
| 基础设施覆盖，可选 | `.env` | 端口、镜像、`STORAGE_BACKEND`、`DATABASE_URL`、构建基础镜像 |
| 应用运行时设置 | `config.json`、首次 `/setup`、Web 管理设置页 | 公开 URL、会话密钥、OIDC、模型网关、NewAPI 绑定、图片存储、审核和安全设置 |

默认本地或测试启动只需要复制 `config.example.json` 为 `config.json`。`.env` 不是必需文件。

`STORAGE_BACKEND` 等基础设施变量由 Docker Compose 传递给容器。可以临时写在命令前：

```bash
STORAGE_BACKEND=postgres \
DATABASE_URL=postgresql://user:password@postgres.example.com:5432/happyimage \
docker compose up -d
```

也可以放在执行 `docker compose` 的目录里的 `.env` 文件中。API-only 部署是在 `happyimage-api/.env`；工作区组合部署是在工作区根目录 `.env`。

部署 `.env` 只保留基础设施项：

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

示例 `model_gateway.gateway_api_base_url` 可以是 `https://gateway.happy-token.cn/v1`。这是上游模型网关 URL，不是 HappyImage API 暴露的兼容入口。

## 配置 OIDC 单点登录

1. 在 OIDC 提供方创建 OAuth 应用，获取 Client ID 和 Client Secret。
2. 在 Web `/setup` 或管理设置页填写公开应用地址、可选公开 API 地址、session secret 和 OIDC 配置。
3. 在 OIDC 提供方设置回调地址：`<api_public_url>/api/auth/oidc/callback`；如果 API 没有独立公开地址，则使用公开应用地址对应的 API 入口。
4. 重启服务或保存设置后重新登录验证。

生产环境注意事项：

- 生产环境跨站登录通常需要 HTTPS，否则浏览器可能拒绝跨站 Cookie。
- Session secret 必须是稳定随机字符串，更换后所有用户会退出登录。
- 管理员账号密码登录不受 OIDC 配置影响；OIDC 配错时可用已有管理员账号进入系统设置。

## 配置 NewAPI 模型网关

如果号池管理、模型调试和上游账号设置已经迁移到 NewAPI，HappyImage API 可以只负责登录、图库、历史会话、私有图片和任务状态。模型供应商不再通过后端 `.env` 统一配置；普通用户登录后会自动获得默认 HappyToken 供应商，也可以在 Web 的“我的 -> 供应商”里添加其他预设或自定义供应商。

NewAPI/HappyToken 自动绑定常用字段：

| 字段 | 说明 |
|:--|:--|
| `model_gateway.gateway_api_base_url` | 上游模型网关 API 地址，例如 `https://gateway.happy-token.cn/v1` |
| `model_gateway.gateway_management_url` | 上游管理入口，例如 `https://gateway.happy-token.cn` |
| `model_gateway.token_name` | 自动创建 token 的名称 |
| `model_gateway.provision_url` | 受控 provisioning endpoint |
| `model_gateway.provision_secret` | provisioning endpoint 鉴权密钥 |
| `model_gateway.sql_dsn` | 可选 NewAPI 数据库直连 DSN |

OIDC 登录会尝试创建或复用 NewAPI 用户/token，并把它写成用户默认 HappyToken 供应商。`/api/auth/session` 会在用户已有 OIDC 身份但绑定仍是 pending/failed 时重试。`/settings/newapi` 是 HappyImage 原生管理页，读取 `/api/auth/newapi-management` 展示绑定状态和默认 API Key；它不依赖 NewAPI iframe 自动登录，因为 SQL/provisioning 不会给浏览器写入 `gateway.happy-token.cn` 的 session cookie。

## Web Docker 运行示例

```bash
docker run -p 3000:3000 \
  -v /srv/happyimage/seed-gallery:/app/web/public/seed-gallery:ro \
  -e BACKEND_URL=https://api.example.com \
  happyimage-web
```

同源代理模式下不要设置 `NEXT_PUBLIC_API_BASE_URL`。让浏览器请求保持为 `/api/*`、`/images/*`、`/image-thumbnails/*` 和 `/health`，由 Web middleware 转发到 `BACKEND_URL`。

官方图库是 Web 静态包，不再内置到 API 镜像。生成或更新静态包请在 Web 项目执行 `pnpm run gallery:build`，或在服务器上挂载已生成的 `seed-gallery` 目录。

## 存储后端

默认 `docker-compose.yml` 使用 `json` 存储，数据保存在 `./data`。生产环境建议显式设置 PostgreSQL。

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
| `../happyimage-gallery-source/image-gallery-seed/` | 官方图库源数据 | 仓库外保存，用于导出 Web 静态包；生产不需要挂载到 API 容器 |

完整迁移示例：

```bash
rsync -av --progress ./data/ user@server:/srv/happyimage-api/data/
rsync -av --progress ./config.json user@server:/srv/happyimage-api/config.json

ssh user@server
cd /srv/happyimage-api
chmod 700 data
chmod 600 config.json
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
docker compose pull
docker compose up -d
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
docker compose logs -f --tail=200 happytoken-api
```

重新构建：

```bash
docker compose build --no-cache happytoken-api
docker compose up -d happytoken-api
```

如果 Docker Desktop 报本地镜像 blob `input/output error`，通常是 Docker 本地镜像存储损坏。可以先尝试删除本项目镜像并重建；如果连 `docker image ls` 都报同类错误，需要重启 Docker Desktop。
