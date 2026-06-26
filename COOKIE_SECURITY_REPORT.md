# OAuth 授权后 Cookie 设置规则分析

OAuth/OIDC 授权后，系统使用签名的 HttpOnly Cookie 保存 Web 会话。Cookie 行为由 `config.json`、首次 `/setup` 或管理员 `/settings` 中的运行时字段控制，而不是部署环境变量。

## Cookie 设置规则

| 属性 | 当前来源 | 说明 |
|:--|:--|:--|
| 名称 | `session_cookie_name`，默认 `happytoken_session` | 会话 Cookie 名称 |
| Domain | `session_cookie_domain` | 空值表示不显式设置 Domain，使用浏览器默认域规则 |
| Max-Age | `session_max_age_seconds`，默认 `86400` | 会话有效期，最小 60 秒 |
| Secure | 根据 `api_public_url` 或 `public_app_url` 是否为 HTTPS 判断 | HTTPS 公开地址会设置 Secure |
| SameSite | 根据公开 API/Web URL 的安全性判断 | HTTPS 跨站场景使用 `None; Secure`，否则使用 `Lax` |
| 签名密钥 | `session_secret` | 必须稳定保存，更换后所有会话失效 |

相关公开 URL：

- `public_app_url`：用户访问 Web 的公开地址。
- `api_public_url`：API 有独立公网域名时填写；为空时使用 `public_app_url`。
- `cors_origins`：允许的 Web 来源；通常包含 `public_app_url`。

## 配置示例

### 单域名 HTTPS

```json
{
  "public_app_url": "https://image.example.com",
  "api_public_url": "",
  "cors_origins": ["https://image.example.com"],
  "session_cookie_domain": "",
  "session_secret": "your-secret-key-here"
}
```

示例 Set-Cookie：

```text
Set-Cookie: happytoken_session=<jwt-token>; HttpOnly; Path=/; Secure; SameSite=None; Max-Age=86400
```

### 跨子域 HTTPS

```json
{
  "public_app_url": "https://app.happy-token.cn",
  "api_public_url": "https://api.happy-token.cn",
  "cors_origins": ["https://app.happy-token.cn"],
  "session_cookie_domain": ".happy-token.cn",
  "session_secret": "your-secret-key-here"
}
```

示例 Set-Cookie：

```text
Set-Cookie: happytoken_session=<jwt-token>; HttpOnly; Path=/; Domain=.happy-token.cn; Secure; SameSite=None; Max-Age=86400
```

### 本地 HTTP

```json
{
  "public_app_url": "http://localhost:3000",
  "api_public_url": "http://localhost:8000",
  "cors_origins": ["http://localhost:3000"],
  "session_cookie_domain": "",
  "session_secret": "local-dev-secret"
}
```

示例 Set-Cookie：

```text
Set-Cookie: happytoken_session=<jwt-token>; HttpOnly; Path=/; SameSite=Lax; Max-Age=86400
```

## 安全建议

- 生产环境使用 HTTPS，并正确设置 `public_app_url` 和可选 `api_public_url`。
- 将 `session_secret` 保存在 `config.json`、`/setup` 或管理员 `/settings` 管理的运行时配置中，并保持稳定。
- 仅在确实需要跨子域共享 Cookie 时设置 `session_cookie_domain`。
- 保持 `cors_origins` 与实际 Web 公开地址一致。
- 部署 `.env` 保持基础设施用途，不再注入会话、公开 URL、OIDC、CORS 或 Cookie 运行时设置。

## 代码位置

| 文件 | 功能 |
|:--|:--|
| [services/web_session_service.py](services/web_session_service.py) | 生成和清除会话 Cookie |
| [api/auth_oidc.py](api/auth_oidc.py) | OIDC 回调和登录重定向 |

## 验证清单

- [ ] `session_secret` 已配置为强密钥。
- [ ] `public_app_url` 和 `api_public_url` 与真实公网 origin 匹配。
- [ ] 前端和后端都使用 HTTPS（如果需要跨域 Cookie）。
- [ ] 如果 API 和前端在不同子域，已评估 `session_cookie_domain` 和 SameSite=None 是否适用。
- [ ] Cookie Max-Age 值符合业务需求。
