<h1 align="center">HappyImage API</h1>

<p align="center">HappyImage 后端 — FastAPI 服务，提供 OpenAI 兼容图片 API、OIDC 认证、会话管理和号池管理。</p>

> [!WARNING]
> 免责声明：
>
> 本项目涉及对 ChatGPT 官网文本生成、图片生成与图片编辑等相关接口的逆向研究，仅供个人学习、技术研究与非商业性技术交流使用。
>
> - 严禁将本项目用于任何商业用途、盈利性使用、批量操作、自动化滥用或规模化调用。
> - 严禁将本项目用于破坏市场秩序、恶意竞争、套利倒卖、二次售卖相关服务，以及任何违反 OpenAI 服务条款或当地法律法规的行为。
> - 使用者应自行承担全部风险，包括但不限于账号被限制、临时封禁或永久封禁以及因违规使用等所导致的法律责任。
> - 本项目基于对 ChatGPT 官网相关能力的逆向研究实现，存在账号受限、临时封禁或永久封禁的风险。请勿使用你自己的重要账号、常用账号或高价值账号进行测试。

## 架构

| 仓库 | 说明 |
|:--|:--|
| **happyimage-api**（本仓库） | FastAPI 后端：API、OIDC 回调、会话管理、号池管理 |
| [happyimage-web](https://github.com/happy-token/happyimage-web) | 前端：Next.js 静态站点，部署到 Cloudflare Pages 或 nginx |

## 快速开始

已发布镜像支持 `linux/amd64` 与 `linux/arm64`。

### Docker 运行（后端 + 前端）

```bash
git clone git@github.com:happy-token/happyimage-api.git
cd happyimage-api
cp .env.example .env
cp config.example.json config.json
# 编辑 .env，至少设置 HAPPYIMAGE_AUTH_KEY
docker compose up -d
```

这会启动两个容器：后端 API（端口 8000）和前端面板（端口 3000）。

### Docker 运行（仅后端）

```bash
docker compose -f docker-compose.local.yml up -d --build
```

### 本地开发

```bash
git clone git@github.com:happy-token/happyimage-api.git
cd happyimage-api
cp config.example.json config.json
uv sync
uv run main.py
# 后端运行在 http://127.0.0.1:8000
```

### OIDC 单点登录

在 `.env` 中配置：

```bash
HAPPYIMAGE_AUTH_KEY=your_secret_key_here
HAPPYIMAGE_SESSION_SECRET=generate-a-random-secret
HAPPYIMAGE_OIDC_ENABLED=true
HAPPYIMAGE_OIDC_ISSUER=https://accounts.google.com
HAPPYIMAGE_OIDC_CLIENT_ID=your-client-id
HAPPYIMAGE_OIDC_CLIENT_SECRET=your-client-secret
HAPPYIMAGE_FRONTEND_BASE_URL=http://localhost:3000
HAPPYIMAGE_API_BASE_URL=http://localhost:8000
HAPPYIMAGE_CORS_ORIGINS=http://localhost:3000
```

详细说明见 [Docker 部署指南](./docs/docker-deployment.md)。

## 环境变量

### 必填

| 变量 | 说明 |
|:--|:--|
| `HAPPYIMAGE_AUTH_KEY` | 管理员认证密钥 |

### 服务地址

| 变量 | 说明 |
|:--|:--|
| `HAPPYIMAGE_BASE_URL` | 对外基础 URL |
| `HAPPYIMAGE_FRONTEND_BASE_URL` | 前端地址（OIDC 回调后重定向） |
| `HAPPYIMAGE_API_BASE_URL` | 后端公开地址（构造 OIDC 回调 URL） |
| `HAPPYIMAGE_CORS_ORIGINS` | 允许的跨域来源，逗号分隔 |

### 会话

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `HAPPYIMAGE_SESSION_SECRET` | 会话签名密钥 | — |
| `HAPPYIMAGE_SESSION_COOKIE_NAME` | Cookie 名 | `happyimage_session` |
| `HAPPYIMAGE_SESSION_MAX_AGE_SECONDS` | 过期时间（秒） | `86400` |

### OIDC

| 变量 | 说明 | 默认值 |
|:--|:--|:--|
| `HAPPYIMAGE_OIDC_ENABLED` | 启用 OIDC | `false` |
| `HAPPYIMAGE_OIDC_ISSUER` | issuer URL | — |
| `HAPPYIMAGE_OIDC_CLIENT_ID` | 客户端 ID | — |
| `HAPPYIMAGE_OIDC_CLIENT_SECRET` | 客户端密钥 | — |
| `HAPPYIMAGE_OIDC_SCOPES` | scope | `openid profile email` |
| `HAPPYIMAGE_OIDC_ALLOWED_EMAIL_DOMAINS` | 邮箱域名限制 | — |
| `HAPPYIMAGE_OIDC_DEFAULT_IMAGE_QUOTA` | 新用户默认额度 | `0` |

## API

所有 AI 接口需要 `Authorization: Bearer <token>` 头。

| 端点 | 说明 |
|:--|:--|
| `GET /v1/models` | 模型列表 |
| `POST /v1/images/generations` | 文生图 |
| `POST /v1/images/edits` | 图片编辑 |
| `POST /v1/chat/completions` | 对话（图片场景） |
| `POST /v1/responses` | Responses API |

`/v1/*` 路由仅接受 Bearer token 认证，不接受 Cookie 会话。

详细 API 文档和部署指南见 [Docker 部署指南](./docs/docker-deployment.md) 和 [README（旧版）](https://github.com/happy-token/HappyImage)。

## 认证

| 通道 | 认证方式 | 适用范围 |
|:--|:--|:--|
| Web UI | HttpOnly Cookie（OIDC 登录）或 Bearer token | `/api/*` |
| 外部 API | `Authorization: Bearer <token>` | `/v1/*`（仅 Bearer） |

管理员恢复路径：使用 `HAPPYIMAGE_AUTH_KEY` 作为访问密钥登录，不受 OIDC 配置影响。

## CI/CD

推送到 main 分支自动构建多架构 Docker 镜像并推送到 Docker Hub。详见 `.github/workflows/build-api.yml`。

## 关联项目

- [happyimage-web](https://github.com/happy-token/happyimage-web) — 前端面板
- [HappyImage（旧 monorepo）](https://github.com/happy-token/HappyImage) — 合并仓库（存档）
