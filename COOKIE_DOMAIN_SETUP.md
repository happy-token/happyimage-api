# Cookie Domain 配置指南

## 快速开始

根据你的部署场景选择合适的配置方式：

### 方案 1：happytoken.workers.dev（Cloudflare Workers）

#### 环境变量方式
```bash
HAPPYTOKEN_SESSION_COOKIE_DOMAIN=happytoken.workers.dev
HAPPYTOKEN_API_BASE_URL=https://happytoken.workers.dev
HAPPYTOKEN_FRONTEND_BASE_URL=https://happytoken.workers.dev
HAPPYTOKEN_SESSION_SECRET=your-strong-secret-here
```

#### config.json 方式
```json
{
  "session_cookie_domain": "happytoken.workers.dev",
  "api_base_url": "https://happytoken.workers.dev",
  "frontend_base_url": "https://happytoken.workers.dev",
  "session_secret": "your-strong-secret-here"
}
```

**结果**：Cookie 仅在 `happytoken.workers.dev` 域中有效

---

### 方案 2：happy-token.cn（跨子域）

#### 环境变量方式
```bash
# 使用 .happy-token.cn 允许所有子域共享 Cookie
HAPPYTOKEN_SESSION_COOKIE_DOMAIN=.happy-token.cn
HAPPYTOKEN_API_BASE_URL=https://api.happy-token.cn
HAPPYTOKEN_FRONTEND_BASE_URL=https://app.happy-token.cn
HAPPYTOKEN_SESSION_SECRET=your-strong-secret-here
```

#### config.json 方式
```json
{
  "session_cookie_domain": ".happy-token.cn",
  "api_base_url": "https://api.happy-token.cn",
  "frontend_base_url": "https://app.happy-token.cn",
  "session_secret": "your-strong-secret-here"
}
```

**结果**：Cookie 在以下所有域中有效：
- `api.happy-token.cn`
- `app.happy-token.cn`
- `gateway.happy-token.cn`
- 以及其他任何 `*.happy-token.cn` 的子域

---

### 方案 3：不设置 Domain（默认 - 最安全）

#### 环境变量方式
```bash
HAPPYTOKEN_SESSION_COOKIE_DOMAIN=
HAPPYTOKEN_API_BASE_URL=https://your-domain.com
HAPPYTOKEN_FRONTEND_BASE_URL=https://your-domain.com
HAPPYTOKEN_SESSION_SECRET=your-strong-secret-here
```

#### config.json 方式
```json
{
  "session_cookie_domain": "",
  "api_base_url": "https://your-domain.com",
  "frontend_base_url": "https://your-domain.com",
  "session_secret": "your-strong-secret-here"
}
```

**结果**：Cookie 仅在设置它的域中有效（默认浏览器行为，最安全）

---

## Docker 部署配置

### docker-compose.yml
```yaml
environment:
  - HAPPYTOKEN_SESSION_COOKIE_DOMAIN=.happy-token.cn
  - HAPPYTOKEN_API_BASE_URL=https://api.happy-token.cn
  - HAPPYTOKEN_FRONTEND_BASE_URL=https://app.happy-token.cn
  - HAPPYTOKEN_SESSION_SECRET=your-strong-secret-here
```

### .env 文件
```bash
HAPPYTOKEN_SESSION_COOKIE_DOMAIN=.happy-token.cn
HAPPYTOKEN_API_BASE_URL=https://api.happy-token.cn
HAPPYTOKEN_FRONTEND_BASE_URL=https://app.happy-token.cn
HAPPYTOKEN_SESSION_SECRET=your-strong-secret-here
```

---

## Domain 值格式说明

| 值 | 含义 | 应用场景 |
|---|---|---|
| `happytoken.workers.dev` | 精确域名匹配 | 单一域名，子域不共享 Cookie |
| `.happy-token.cn` | 主域名 + 所有子域 | 多个子域（推荐） |
| `happy-token.cn` | 主域名（通常等同于 `.happy-token.cn`） | 主域名 |
| `""` 或空值 | 不设置 Domain 属性 | 默认浏览器规则（最安全）|

---

## 常见问题

### Q: 设置 Domain 后为什么 Cookie 还是不共享？

**可能原因**：
1. **SameSite 限制** - 确保前后端都使用 HTTPS，SameSite 会自动设置为 `None`
2. **子域名错误** - 检查域名是否正确（例如 `.happy-token.cn` 中的点很重要）
3. **Protocol 不匹配** - 确保 API 和前端都是 HTTPS 或都是 HTTP
4. **缓存问题** - 清空浏览器 Cookie 和缓存后重试

### Q: 如何验证 Cookie Domain 是否生效？

在浏览器开发者工具中检查 Cookie：
1. 打开 DevTools (F12)
2. 进入 Application → Cookies
3. 查看 Cookie 的 Domain 列，应该显示你配置的值

示例：
- 配置 `.happy-token.cn` → 显示 `.happy-token.cn`
- 不配置 → 显示具体的域名（如 `app.happy-token.cn`）

### Q: 生产环境是否必须配置 Domain？

**不一定**：
- 如果 API 和前端在同一域名 → 无需配置
- 如果 API 和前端在不同子域 → 需要配置 Domain
- 在不同的顶级域名 → 无法通过 Cookie 共享（需要其他方案）

---

## 安全检查清单

部署前验证：

- [ ] `HAPPYTOKEN_SESSION_SECRET` 已设置为强密钥
- [ ] API 和前端都使用 HTTPS（`https://`）
- [ ] 如果跨子域，Domain 值正确配置
- [ ] 已在本地测试 Cookie 是否正常工作
- [ ] 生产环境中 Domain 值与实际部署域名匹配
- [ ] CORS 配置与 Domain 配置一致

---

## 相关文档

- [Cookie 安全分析报告](COOKIE_SECURITY_REPORT.md)
- [docker-compose 部署指南](docs/docker-deployment.md)
- [应用架构说明](docs/architecture.md)
