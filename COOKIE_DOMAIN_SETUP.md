# Cookie Domain 配置指南

Cookie、公开 URL、会话密钥和 CORS 不再作为部署环境变量维护。请通过 `config.json`、首次 `/setup` 或管理员 `/settings` 配置以下字段：

```json
{
  "public_app_url": "https://app.happy-token.cn",
  "api_public_url": "https://api.happy-token.cn",
  "cors_origins": ["https://app.happy-token.cn"],
  "session_secret": "your-strong-secret-here",
  "session_cookie_domain": ".happy-token.cn",
  "session_cookie_name": "happytoken_session",
  "session_max_age_seconds": 86400
}
```

## 常见场景

### 单域名部署

Web 和 API 在同一个浏览器 origin 下时，推荐不设置 Cookie Domain：

```json
{
  "public_app_url": "https://image.example.com",
  "api_public_url": "",
  "cors_origins": ["https://image.example.com"],
  "session_cookie_domain": "",
  "session_secret": "your-strong-secret-here"
}
```

结果：Cookie 仅在设置它的域中有效，这是最安全的默认浏览器行为。

### 跨子域部署

Web 和 API 位于同一主域下的不同子域时，可以设置共享 Domain：

```json
{
  "public_app_url": "https://app.happy-token.cn",
  "api_public_url": "https://api.happy-token.cn",
  "cors_origins": ["https://app.happy-token.cn"],
  "session_cookie_domain": ".happy-token.cn",
  "session_secret": "your-strong-secret-here"
}
```

结果：Cookie 可在 `*.happy-token.cn` 子域间共享。生产环境应使用 HTTPS。

### Workers / 单一公开域名

```json
{
  "public_app_url": "https://happytoken.workers.dev",
  "api_public_url": "https://happytoken.workers.dev",
  "cors_origins": ["https://happytoken.workers.dev"],
  "session_cookie_domain": "happytoken.workers.dev",
  "session_secret": "your-strong-secret-here"
}
```

## Docker 部署

Compose 和 `.env` 只应保留基础设施变量，例如 `STORAGE_BACKEND`、`DATABASE_URL`、端口和镜像名。不要在 compose 或私有 `.env` 中注入会话、公开 URL、OIDC 或 CORS 运行时设置。

## 验证

在浏览器开发者工具中检查 Cookie：

1. 打开 DevTools。
2. 进入 Application -> Cookies。
3. 查看 Cookie 的 Domain、Secure、SameSite 和 Max-Age。

部署前检查：

- [ ] `session_secret` 已在 `config.json`、`/setup` 或管理员 `/settings` 中设置为强密钥。
- [ ] `public_app_url` 和可选 `api_public_url` 与实际访问 origin 一致。
- [ ] 如果跨子域共享 Cookie，`session_cookie_domain` 与实际域名匹配。
- [ ] `cors_origins` 包含 Web 公开地址。
- [ ] 生产环境使用 HTTPS。

## 相关文档

- [Cookie 安全分析报告](COOKIE_SECURITY_REPORT.md)
- [docker-compose 部署指南](docs/docker-deployment.md)
- [应用架构说明](docs/architecture.md)
