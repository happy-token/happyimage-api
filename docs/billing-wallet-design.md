# 钱包与计费账本设计

HappyImage 后续不应该只维护 `image_quota`。用户既可能生成图片，也可能使用文本、搜索、视频、编辑等能力，这些都需要统一进入一个钱包账本。

## 推荐模型

保留一个用户钱包，钱包里有一种统一余额单位，例如 `credits`：

```text
1 元充值 -> N credits
图片生成 -> 按张扣 credits
Token 调用 -> 按模型和 token 数扣 credits
失败任务 -> 原路退回 credits
```

`image_quota` 可以继续保留一段时间作为兼容字段，但新计费应逐步迁移到 `wallet_balance` + `ledger`。

## 核心表/记录

### Wallet

每个 HappyImage 用户一条钱包记录：

```json
{
  "user_id": "happyimage-user-id",
  "balance": 1000,
  "currency": "credits",
  "updated_at": "2026-06-20T12:00:00Z"
}
```

### Ledger

所有充值、扣费、退款都写入流水。余额可以从流水重算，也可以缓存到 Wallet：

```json
{
  "id": "ledger-id",
  "user_id": "happyimage-user-id",
  "type": "charge|consume|refund|adjust",
  "source": "newapi|image_generation|token_usage|admin",
  "amount": 100,
  "balance_after": 900,
  "external_order_id": "newapi-order-id",
  "idempotency_key": "unique-key",
  "metadata": {
    "model": "gpt-image-2",
    "image_count": 1,
    "prompt_tokens": 0,
    "completion_tokens": 0
  },
  "created_at": "2026-06-20T12:00:00Z"
}
```

## 图片计费

图片生成建议按任务预扣：

1. 计算预计价格。
2. 创建任务前预扣钱包余额。
3. 生成成功，确认扣费。
4. 生成失败，写退款流水。

示例价格：

```text
普通图片：1 张 = 10 credits
高清图片：1 张 = 20 credits
编辑图片：1 次 = 10 credits
```

## Token 计费

Token 类调用建议按模型价格表计算：

```text
消费 credits = input_tokens * input_price + output_tokens * output_price
```

价格表要放在系统配置或数据库里，不要写死在业务代码中。

## New API 的角色

New API 负责收款和订单，不直接负责 HappyImage 的 Web 逆向生图扣费。

推荐链路：

```text
New API 支付成功
  -> 回调 HappyImage
  -> HappyImage 写入 charge 流水
  -> 增加 wallet balance
```

HappyImage 的所有能力消费都只扣 HappyImage 钱包。

## 为什么不直接复用 New API 额度

New API 对普通模型网关很合适，但 HappyImage 当前的生图能力来自 Web 逆向账号池。New API 不知道：

- 使用了哪个 Web 逆向账号
- 图片是否最终成功
- 一次任务生成了几张图
- 是否需要退款
- 是否命中本地缓存或重试

所以 HappyImage 必须维护自己的消费账本。

## 迁移路线

第一阶段：

- 继续保留 `image_quota`
- New API 回调仍然增加图片额度
- 文档和配置先统一到 Casdoor/OIDC

第二阶段：

- 新增 `wallet_balance` 和 `ledger`
- 图片生成从扣 `image_quota` 改为扣 `credits`
- 充值回调从增加图片额度改为增加钱包余额

第三阶段：

- 接入 Token 类能力
- 增加模型价格表
- 管理员后台显示用户余额、消费流水、充值订单和退款记录
