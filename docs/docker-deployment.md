# Docker 部署指南

本文说明 HappyImage 使用 Docker Compose 启动、升级和排障的常用流程。生产主机、远程路径、账号、密钥和代理地址请放在 `.env` 或服务器私有配置中，不要提交到 git。

## 架构

HappyImage 由两个独立服务组成：

| 服务 | 容器名 | 默认端口 | 说明 |
|:--|:--|:--|:--|
| `happyimage-api` | `happyimage-api` | `8000` | FastAPI 后端：API、OIDC 回调、会话管理 |
| `happyimage-web` | `happyimage-web` | `3000` | 前端静态服务：Next.js + nginx |

前端通过 HTTP API 与后端通信。浏览器用户使用 HttpOnly Cookie 会话（OIDC 登录）或 Bearer token（密码/密钥登录）；外部 API 客户端使用 `Authorization: Bearer <token>`。

## 文件说明

| 文件 | 用途 |
|:--|:--|
| `docker-compose.yml` | 默认双服务配置，`happyimage-api`（端口 8000）+ `happyimage-web`（端口 3000） |
| `docker-compose.local.yml` | 本地调试 / 单容器兼容配置，前后端合并为一个容器，端口 8000 |
| `.env.example` | 环境变量模板，复制为 `.env` 后填写本机或服务器配置 |
| `config.example.json` | 应用配置模板，复制为 `config.json` 后可在设置页继续维护 |
| `data/` | 运行数据目录，包含账号、日志、图片任务、缓存图片和图库种子数据 |

## 首次启动

```bash
cp .env.example .env
cp config.example.json config.json
```

编辑 `.env`，至少设置：

```bash
HAPPYIMAGE_AUTH_KEY=replace_with_a_strong_secret
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
| Web 面板 | `http://localhost:3000` |
| API 地址 | `http://localhost:8000/v1` |
| 健康检查 | `http://localhost:8000/health?format=json` |

## 单容器部署（兼容旧版）

如果不需要前后端分离，可以使用本地开发 compose 文件：

```bash
docker compose -f docker-compose.local.yml up -d --build
curl -sf http://localhost:8000/health?format=json
```

启动后 Web 面板和 API 都在 `http://localhost:8000`。

## 配置 OIDC 单点登录

### 步骤

1. 在 OIDC 提供方（如 Google、Azure AD、Keycloak）创建 OAuth 应用，获取 Client ID 和 Client Secret
2. 设置回调地址：`<HAPPYIMAGE_API_BASE_URL>/api/auth/oidc/callback`
   例如：`https://api.example.com/api/auth/oidc/callback`
3. 在 `.env` 中配置：

```bash
# 必填
HAPPYIMAGE_SESSION_SECRET=generate-a-random-secret-at-least-32-chars

# OIDC 提供方配置
HAPPYIMAGE_OIDC_ENABLED=true
HAPPYIMAGE_OIDC_ISSUER=https://accounts.google.com
HAPPYIMAGE_OIDC_CLIENT_ID=your-client-id.apps.googleusercontent.com
HAPPYIMAGE_OIDC_CLIENT_SECRET=GOCSPX-your-client-secret

# 服务地址
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

5. 登录页会出现「通过 OIDC 单点登录」按钮
6. 首次 OIDC 登录会自动创建用户，默认图片额度为配置值

### 生产部署注意事项

- **HTTPS 必需**：生产环境前后端在不同站点时，会话 Cookie 需要 `Secure` 和 `SameSite=None`，因此 HTTP 不可用
- **CORS 必需**：必须配置 `HAPPYIMAGE_CORS_ORIGINS` 为前端地址
- **会话密钥**：`HAPPYIMAGE_SESSION_SECRET` 必须是随机字符串，重启后更换会导致所有用户退出登录
- **恢复路径**：管理员本地密码 / 访问密钥登录不受 OIDC 配置影响，如果 OIDC 配置错误导致无法登录，可使用管理员密码登录修复

## 配置优先级

`HAPPYIMAGE_AUTH_KEY`、`HAPPYIMAGE_PROXY`、`HAPPYIMAGE_BASE_URL` 等环境变量会覆盖 `config.json` 中的对应值。推荐把密钥、代理和部署域名放在 `.env`，把功能开关和运行参数放在 `config.json` 或 Web 设置页。

OIDC 配置在 Web 设置页修改后，Client Secret 会脱敏显示（仅显示"已配置"或"未配置"）。保存时如果留空 Client Secret，保持旧值不变；填入新值则替换。

## 环境变量参考

### 必填

| 变量 | 说明 |
|:--|:--|
| `HAPPYIMAGE_AUTH_KEY` | 管理员认证密钥，也是默认管理员登录密码 |

### 服务地址与 CORS

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `HAPPYIMAGE_BASE_URL` | 对外基础 URL，图片返回绝对地址 | — |
| `HAPPYIMAGE_FRONTEND_BASE_URL` | 前端公开地址，OIDC 登录后重定向目标 | — |
| `HAPPYIMAGE_API_BASE_URL` | 后端公开地址，构造 OIDC 回调 URL | — |
| `HAPPYIMAGE_CORS_ORIGINS` | 允许的跨域来源，逗号分隔 | `HAPPYIMAGE_FRONTEND_BASE_URL` |

### 会话

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `HAPPYIMAGE_SESSION_SECRET` | 会话签名密钥（OIDC 登录必需） | — |
| `HAPPYIMAGE_SESSION_COOKIE_NAME` | 会话 Cookie 名称 | `happyimage_session` |
| `HAPPYIMAGE_SESSION_MAX_AGE_SECONDS` | 会话过期时间（秒） | `86400`（24 小时） |

### OIDC

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `HAPPYIMAGE_OIDC_ENABLED` | 是否启用 OIDC 登录 | `false` |
| `HAPPYIMAGE_OIDC_ISSUER` | OIDC 提供方 issuer URL | — |
| `HAPPYIMAGE_OIDC_CLIENT_ID` | OAuth 客户端 ID | — |
| `HAPPYIMAGE_OIDC_CLIENT_SECRET` | OAuth 客户端密钥 | — |
| `HAPPYIMAGE_OIDC_SCOPES` | 请求的 scope | `openid profile email` |
| `HAPPYIMAGE_OIDC_ALLOWED_EMAIL_DOMAINS` | 允许的邮箱域名（逗号分隔，留空不限制） | — |
| `HAPPYIMAGE_OIDC_DEFAULT_IMAGE_QUOTA` | OIDC 新用户默认图片额度 | `0` |

### 注册与代理

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `HAPPYIMAGE_REGISTRATION_ENABLED` | 是否开放普通用户注册 | `true` |
| `HAPPYIMAGE_PROXY` | 上游代理 URL | — |
| `HAPPYIMAGE_PREGENERATE_THUMBNAILS_ON_START` | 启动时预生成图库缩略图 | `true` |
| `HAPPYIMAGE_THUMBNAIL_WIDTHS` | 缩略图宽度 | `640` |

### 存储

| 变量 | 说明 |
|:--|:--|
| `STORAGE_BACKEND` | 存储后端，可选 `json`、`sqlite`、`postgres`、`git` |
| `DATABASE_URL` | SQLite 或 PostgreSQL 连接地址 |
| `GIT_REPO_URL`、`GIT_TOKEN` | Git 存储的仓库地址和访问令牌 |

## 存储后端

默认 `docker-compose.yml` 使用 `json` 存储，数据保存在 `./data`。本地调试配置 `docker-compose.local.yml` 默认使用 SQLite。

PostgreSQL 示例：

```bash
STORAGE_BACKEND=postgres
DATABASE_URL=postgresql://user:password@postgres.example.com:5432/happyimage
```

Git 存储示例：

```bash
STORAGE_BACKEND=git
GIT_REPO_URL=https://github.com/your-username/your-private-repo.git
GIT_TOKEN=your_token_here
GIT_BRANCH=main
GIT_FILE_PATH=accounts.json
```

## 代理配置

容器访问宿主机 Clash / mihomo 代理时，通常使用 `host.docker.internal`：

```bash
HAPPYIMAGE_PROXY=http://host.docker.internal:7897
```

如果 Docker Desktop 构建阶段没有继承系统代理，可以只给本次构建设置代理：

```bash
HTTP_PROXY=http://127.0.0.1:7897 \
HTTPS_PROXY=http://127.0.0.1:7897 \
docker compose up -d --build
```

## 升级

### 双服务模式

```bash
git pull
docker compose build happyimage-api happyimage-web
docker compose up -d happyimage-api happyimage-web
docker compose ps
curl -sf http://localhost:8000/health?format=json
```

### 单容器模式

```bash
git pull
docker compose -f docker-compose.local.yml build
docker compose -f docker-compose.local.yml up -d
```

升级前建议备份 `config.json` 和 `data/`。如果使用外部 PostgreSQL 或 Git 存储，也要按对应后端的方式做备份。

## 从单容器迁移到双服务

1. 拉取最新代码：`git pull`
2. 备份 `config.json` 和 `data/`
3. 在 `.env` 中配置服务地址：

```bash
HAPPYIMAGE_FRONTEND_BASE_URL=http://localhost:3000
HAPPYIMAGE_API_BASE_URL=http://localhost:8000
HAPPYIMAGE_CORS_ORIGINS=http://localhost:3000
```

4. 构建并启动双服务：

```bash
docker compose build happyimage-api happyimage-web
docker compose up -d happyimage-api happyimage-web
```

5. 验证：

```bash
curl -sf http://localhost:8000/health?format=json
curl -sf http://localhost:3000/
```

6. 确认可用后，停止旧容器。

> 迁移时 `data/` 和 `config.json` 无需修改——两个架构共享同一套数据目录。

## 日志和排障

查看服务状态：

```bash
docker compose ps
```

查看特定服务日志：

```bash
docker compose logs -f --tail=200 happyimage-api
docker compose logs -f --tail=200 happyimage-web
```

查看全部日志：

```bash
docker compose logs -f --tail=200
```

重新构建：

```bash
docker compose build --no-cache happyimage-api
docker compose up -d happyimage-api
```

如果 Docker Desktop 报本地镜像 blob `input/output error`，通常是 Docker 本地镜像存储损坏。可以先尝试删除本项目镜像并重建：

```bash
docker image rm happyimage-api:latest happyimage-web:latest
docker compose build --no-cache
docker compose up -d
```

如果连 `docker image ls` 都报同类错误，需要重启 Docker Desktop；仍无法恢复时，再考虑清理 Docker Desktop 的构建缓存或重置本地镜像数据。

### 常见问题

**OIDC 登录后会话立即失效**

检查：
- `HAPPYIMAGE_SESSION_SECRET` 是否已设置
- `HAPPYIMAGE_FRONTEND_BASE_URL` 和 `HAPPYIMAGE_API_BASE_URL` 是否正确
- 生产环境是否使用 HTTPS（跨站 Cookie 需要 Secure）
- `HAPPYIMAGE_CORS_ORIGINS` 是否包含前端地址

**OIDC 回调返回"state 不匹配"**

通常是用户在浏览器中打开了两次授权页面。重新点击登录按钮即可。

**管理员无法登录**

管理员本地密码 / 访问密钥登录不受 OIDC 配置影响。使用 `HAPPYIMAGE_AUTH_KEY` 作为访问密钥即可登录修复配置。
