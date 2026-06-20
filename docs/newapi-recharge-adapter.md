# New API 充值适配

HappyImage 不直接在前端调用 New API 的支付接口。前端只请求 HappyImage，HappyImage 返回 New API 充值中心地址；支付完成后，New API 通过回调通知 HappyImage 增加用户图片额度。

## 统一登录

HappyImage 和 New API 应该同时接入同一个 Casdoor/OIDC 应用体系，使用同一个用户 `sub` 或邮箱作为跨系统身份键：

```text
用户 -> Casdoor/OIDC
  -> New API 用户
  -> HappyImage 用户
```

HappyImage 保存 OIDC 用户的：

- `auth_provider`: 固定为 `oidc`
- `auth_subject`: OIDC `sub`
- `email`: OIDC 邮箱

充值跳转时，HappyImage 会把 `happyimage_user_id`、`external_subject` 和 `email` 带给 New API。支付回调时，HappyImage 按这些字段匹配用户。

## 推荐链路

1. 用户在 HappyImage 点击充值。
2. HappyImage 前端请求 `GET /api/recharge/session`。
3. HappyImage 后端返回 New API 充值页地址，例如 `https://new-api.example.com/console/topup?...`。
4. 用户在 New API 完成支付。
5. New API 调用 HappyImage `POST /api/recharge/newapi/webhook`。
6. HappyImage 按用户 ID、OIDC subject 或邮箱找到用户并增加 `image_quota`。

## HappyImage 配置

可以在管理员设置页的“充值与 New API”中配置，也可以使用环境变量：

```env
HAPPYIMAGE_RECHARGE_ENABLED=true
HAPPYIMAGE_RECHARGE_PROVIDER=newapi
HAPPYIMAGE_NEWAPI_BASE_URL=https://new-api.example.com
HAPPYIMAGE_NEWAPI_CONSOLE_TOPUP_PATH=/console/topup
HAPPYIMAGE_RECHARGE_WEBHOOK_SECRET=replace-with-a-shared-secret
HAPPYIMAGE_RECHARGE_QUOTA_PER_UNIT=1
```

`HAPPYIMAGE_RECHARGE_QUOTA_PER_UNIT` 只在回调没有显式传 `quota`、只传 `amount` 时使用。

## 前端会调用的接口

```http
GET /api/recharge/session
Cookie: happyimage_session=...
```

返回示例：

```json
{
  "enabled": true,
  "provider": "newapi",
  "mode": "redirect",
  "quota": 20,
  "recharge_url": "https://new-api.example.com/console/topup?source=happyimage&happyimage_user_id=abc123&return_url=...",
  "message": "前往 New API 充值中心完成支付，支付成功后额度将同步到 HappyImage。"
}
```

## New API 支付成功回调

```http
POST /api/recharge/newapi/webhook
Content-Type: application/json
X-HappyImage-Recharge-Secret: replace-with-a-shared-secret
```

请求体示例：

```json
{
  "status": "paid",
  "order_id": "newapi-order-123",
  "happyimage_user_id": "abc123",
  "external_subject": "casdoor-user-sub",
  "auth_provider": "oidc",
  "email": "user@example.com",
  "quota": 100
}
```

用户匹配优先级：

1. `happyimage_user_id`
2. `auth_provider` + `external_subject`
3. `email`

如果只传金额，也可以传：

```json
{
  "status": "paid",
  "order_id": "newapi-order-123",
  "happyimage_user_id": "abc123",
  "amount": 100
}
```

这时 HappyImage 会按 `amount * HAPPYIMAGE_RECHARGE_QUOTA_PER_UNIT` 增加额度。

## New API 侧注意事项

New API 当前的用户充值接口在 `/api/user/topup/*` 和 `/api/user/*/pay` 下，通常依赖 New API 用户登录态。因此 HappyImage 不应该把 New API 的用户 API 或管理密钥暴露给浏览器。生产推荐让两边都使用同一套 Casdoor/OIDC 登录，然后通过回调把支付结果同步回 HappyImage。
