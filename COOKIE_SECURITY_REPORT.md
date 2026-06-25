# OAuth 授权后 Cookie 设置规则分析

## 概览
OAuth/OIDC 授权后，系统使用签名的 JWT 令牌存储在 HttpOnly Cookie 中进行会话管理。

## Cookie 设置规则

### 📋 基本配置

| 属性 | 值 | 来源 | 说明 |
|------|-----|------|------|
| **名称** | `happytoken_session` | 默认 | 可通过 `HAPPYTOKEN_SESSION_COOKIE_NAME` 环境变量或 `config.json` 配置 |
| **路径** | `/` | 硬编码 | 根路径，对所有应用路由有效 |
| **Domain** | 可配置 | 环境变量/配置 | 通过 `HAPPYTOKEN_SESSION_COOKIE_DOMAIN` 或 `config.json` 的 `session_cookie_domain` 配置（空值表示不设置） |

### 🔒 安全属性

#### HttpOnly
- **值**：始终设置 ✅
- **作用**：防止 JavaScript 通过 `document.cookie` 访问
- **位置**：[services/web_session_service.py](services/web_session_service.py#L169)

#### Secure
- **值**：条件设置
- **规则**：
  - 如果 `api_base_url` 使用 `https://` → 设置 ✅
  - 如果 `api_base_url` 使用 `http://` → 未设置 ❌
- **配置**：`HAPPYTOKEN_API_BASE_URL` 环境变量
- **位置**：[services/web_session_service.py](services/web_session_service.py#L171)

#### SameSite
- **规则**：
  ```
  if (api_base_url 不安全 OR 前端不是 https):
      SameSite=Lax
  else:
      SameSite=None
  ```
- **逻辑**：
  - `Lax` - 仅在安全级别不足时使用，防止某些跨域请求携带 Cookie
  - `None` - 在前后端都使用 HTTPS 时允许跨域 Cookie 传递（需配合 `Secure` 标志）
- **配置**：
  - `HAPPYTOKEN_API_BASE_URL` - API 端点
  - `HAPPYTOKEN_FRONTEND_BASE_URL` - 前端 URL
- **位置**：[services/web_session_service.py](services/web_session_service.py#L160-L162)

### ⏱️ 生命周期

| 属性 | 值 | 配置 |
|------|-----|------|
| **Max-Age** | 86400 秒（24小时） | `HAPPYTOKEN_SESSION_MAX_AGE_SECONDS` 环境变量或 `config.json` 的 `session_max_age_seconds` |
| **最小值** | 60 秒 | 硬编码限制 |

## 关键发现与安全建议

### ✅ Domain 现已支持配置
```
配置项：HAPPYTOKEN_SESSION_COOKIE_DOMAIN 或 config.json 的 session_cookie_domain
支持值：happytoken.workers.dev 或 happy-token.cn 等
空值表示不设置 Domain 属性（使用浏览器隐式域规则）
```

**含义**：
- 设置 Domain 时，Cookie 将在该域及其所有子域中有效
- 例如，设置 `Domain=.happy-token.cn` 后，Cookie 会被发送到 `api.happy-token.cn` 和 `app.happy-token.cn`
- 不设置 Domain 时，Cookie 仅在设置它的域中有效（更安全的默认行为）

**配置建议**：
- ✅ **跨子域共享**：需要在不同子域间共享 Cookie → 设置为 `.happy-token.cn` 或 `happytoken.workers.dev`
- ✅ **单域名应用**：API 和前端在同一域名 → 留空（不设置 Domain）
- ⚠️ **前后端分离**：API 和前端在完全不同的域 → 需要结合 SameSite=None 和 HTTPS

### 🔐 HTTPS 依赖
- 生产环境应配置 `HAPPYTOKEN_API_BASE_URL=https://...`
- 否则 `Secure` 标志不会被设置，Cookie 可在 HTTP 上传输（存在中间人攻击风险）

### 🌐 跨域场景
当前 SameSite 策略：
- 如果后端 HTTPS + 前端 HTTPS → `SameSite=None; Secure`（允许跨域）
- 其他情况 → `SameSite=Lax`（限制跨域）

## 代码位置

| 文件 | 位置 | 功能 |
|------|------|------|
| [services/web_session_service.py](services/web_session_service.py#L165-L176) | `make_set_cookie_header()` | 生成 Set-Cookie 头 |
| [services/web_session_service.py](services/web_session_service.py#L179-L188) | `make_clear_cookie_header()` | 生成清除 Cookie 的 Set-Cookie 头 |
| [api/auth_oidc.py](api/auth_oidc.py#L168) | OIDC 回调处理 | OAuth 授权后设置 Cookie |
| [api/auth_oidc.py](api/auth_oidc.py#L382) | 重定向响应 | 返回 Set-Cookie 头 |

## 完整 Set-Cookie 示例

### 生产环境（HTTPS）+ 配置 Domain

#### happytoken.workers.dev
```
Set-Cookie: happytoken_session=<jwt-token>; HttpOnly; Path=/; Domain=happytoken.workers.dev; Secure; SameSite=None; Max-Age=86400
```

#### happy-token.cn（跨子域）
```
Set-Cookie: happytoken_session=<jwt-token>; HttpOnly; Path=/; Domain=.happy-token.cn; Secure; SameSite=None; Max-Age=86400
```

### 生产环境（HTTPS）+ 不设置 Domain
```
Set-Cookie: happytoken_session=<jwt-token>; HttpOnly; Path=/; Secure; SameSite=None; Max-Age=86400
```

### 开发环境（HTTP）
```
Set-Cookie: happytoken_session=<jwt-token>; HttpOnly; Path=/; SameSite=Lax; Max-Age=86400
```

## 配置环境变量参考

```bash
# Cookie 名称（默认：happytoken_session）
HAPPYTOKEN_SESSION_COOKIE_NAME=custom_session_name

# Cookie Domain（默认：不设置）
# 用于跨域或跨子域共享 Cookie
# 值示例：happytoken.workers.dev 或 .happy-token.cn 或 happy-token.cn
HAPPYTOKEN_SESSION_COOKIE_DOMAIN=.happy-token.cn

# Cookie 最大存活时间（默认：86400 秒 = 24小时）
HAPPYTOKEN_SESSION_MAX_AGE_SECONDS=43200

# API 基础 URL（影响 Secure 和 SameSite 设置）
HAPPYTOKEN_API_BASE_URL=https://api.happy-token.cn

# 前端基础 URL（影响 SameSite 设置）
HAPPYTOKEN_FRONTEND_BASE_URL=https://app.happy-token.cn

# 会话签名密钥（必须配置）
HAPPYTOKEN_SESSION_SECRET=your-secret-key-here
```

## 验证清单

- [ ] 生产环境已配置 `HAPPYTOKEN_API_BASE_URL=https://...`
- [ ] `HAPPYTOKEN_SESSION_SECRET` 已安全配置
- [ ] 前端和后端都使用 HTTPS（如果需要跨域 Cookie）
- [ ] 如果 API 和前端在不同子域，已评估 SameSite=None 是否适用
- [ ] Cookie Max-Age 值符合业务需求（默认 24 小时）
