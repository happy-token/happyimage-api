# 图片生成服务产品调研与图库建设规划

更新时间：2026-06-12

## 1. 结论

建议第一阶段聚焦“图片灵感图库 + 一键复刻 + 聊天式改图工作台”，不要一开始做成 Magnific / Krea / OpenArt 那种全模态创作套件。

原因：

- 图片生成产品已经从“单 prompt 生成一张图”进入“图库、模板、编辑、放大、视频联动、团队资产、API”的平台竞争。
- 新产品早期最容易获得流量的位置不是模型能力本身，而是“好看的图 + 可复制 prompt + 立即生成”的内容入口。
- 中文市场对电商主图、广告海报、写真头像、社媒封面、产品包装、节日热点模板有强需求，图库比空白输入框更容易让用户开始。
- 当前项目已有图片生成、图片编辑、多图组图、会话历史、模型选择、任务追踪等能力，适合把后端能力包装成面向普通用户的创作产品。

推荐定位：

> 面向中文创作者、电商运营、自媒体和设计师的 AI 图片灵感与生成工作台：先看图找灵感，再一键复刻，最后在聊天里持续修改。

## 2. 市场与用户趋势

### 2.1 用户一般怎么用图片生成

从竞品结构、提示词库和 2026 年教程内容看，主流使用方式集中在：

- 电商与商品图：上传普通商品图，生成主图、详情页、场景图、包装图、海报图。
- 广告创意：食品饮料、香水美妆、珠宝、鞋服、汽车、消费电子等商业海报。
- 人像写真：证件照、职业头像、复古写真、情侣照、旅行照、写真风格迁移。
- 社媒内容：小红书封面、短视频封面、Instagram/TikTok/Reels 竖图。
- 角色与 IP：一致角色、多场景角色、3D 手办、玩具包装、头像。
- 设计素材：Logo、品牌视觉、包装 mockup、UI mockup、宣传 Banner。
- 灵感搜索：用户先逛图，看到喜欢的效果后复制 prompt 或点 Remix。

OpenArt 的 prompt 指南把常见 prompt 分成肖像、风景、产品、Logo、动漫、概念艺术、建筑、食物、赛博朋克、复古等 10 类；Adobe Firefly 也把 prompt 示例分为写实摄影、插画艺术、设计品牌、3D 渲染、实验创意等方向。LTX 的 2026 prompt 指南强调好 prompt 需要明确主体、风格、构图、光线、色彩、技术规格与负面约束。

### 2.2 产品竞争不只看模型

Tom's Guide 在 2026 年图片生成器评测中指出，现在平台差异不只是模型强弱，而是生成器外面的创作工具：编辑画布、局部重绘、放大、角色一致性、内置工作流等。Zapier 的 2026 清单也把 ChatGPT、Nano Banana、Midjourney、Ideogram、FLUX、Adobe Firefly、Recraft 分别按“整体质量、Google 生态、艺术效果、文字准确、控制能力、照片编辑整合、图形设计”等维度定位。

因此我们的差异化不应写成“我也能生成图”，而应是：

- 中文 prompt 和中文场景更好用。
- 图库更适合电商、自媒体、广告转化。
- 用户不用懂 prompt，点图即可生成同款。
- 登录后能像聊天一样不断改图。
- 素材、prompt、历史、收藏、项目能沉淀。

## 3. 竞品分层

### 3.1 全能创作平台

| 产品 | 核心定位 | 图片相关能力 | 借鉴点 | 不宜照搬点 |
|---|---|---|---|---|
| Magnific / Freepik | AI Creative Platform | 图片生成、编辑、放大、扩图、背景移除、Relight、Change Camera、素材库、API、MCP、团队 Spaces | 高级首页视觉、按工作流包装、团队/企业付费、素材库连接 | 产品太重，早期不适合做全模态与企业协作 |
| Krea | 图/视频/3D 创意套件 | 文生图、实时生成、图片增强、背景移除、编辑、LoRA、素材管理、22K 放大 | 工具集合、实时画布、模型聚合、免费每日额度 | 技术与模型供应链复杂，MVP 不应铺太宽 |
| OpenArt | AI Creator Studio | 图、视频、音频、角色、一键故事、100+ 模型、编辑套件 | “故事/角色/品牌世界”包装方式、积分套餐、并发生成 | 太泛娱乐化，容易分散图片图库主线 |
| Leonardo.Ai | 图像、艺术、视频生成平台 | 多模型、预设、集合、个人模型训练、团队 token、API | token 体系、公开/私密作品、模型/预设教育 | 功能很多，学习成本较高 |

### 3.2 Prompt 图库与流量入口

| 产品 | 核心定位 | 借鉴点 | 风险 |
|---|---|---|---|
| MeiGen | GPT Image / Nano Banana prompt gallery | 首页直接展示热门图、模型、作者、点赞、浏览、详情页、复制/生成 | 用户生成内容授权不清，不能直接搬运为商用素材 |
| OpenNana | 中文 prompt 图库 + 生成入口 | 中文导航清晰：提示词库、AI 生图、生成记录、会员计划、收藏；有模型和标签筛选 | 需要做内容审核、去重和版权标记 |
| Proxima Prompts | 免费 prompt gallery | 1371 个 prompt，模型和风格标签非常丰富，支持 shuffle/newest/popular | 页面声明 all rights reserved，适合研究结构，不适合直接下载复用 |
| OpenArt Blog Prompts | 文章式 prompt 模板 | 按场景教学，说明 prompt 结构和模型选择 | 文章内容不应全文搬运，可学习分类和写法 |

### 3.3 模型/能力型竞品

| 产品/模型 | 强项 | 对产品规划的启发 |
|---|---|---|
| ChatGPT / GPT Image | 对话式改图、复杂指令、产品/海报/文字布局 | 工作台应以聊天式交互为主 |
| Nano Banana / Gemini | 快速编辑、参考图融合、用户传播强 | 做“上传自拍/商品图变风格”的模板入口 |
| Midjourney | 审美强、社区灵感强 | 图库要重视美感排序和社区传播 |
| Ideogram | 图中文字准确，适合海报、Logo、印刷 | 海报/营销图应提供文字准确模型选项 |
| Adobe Firefly | 与 Photoshop、设计工作流结合，商业安全感强 | 商业化必须重视版权、商标、人物肖像和素材授权 |
| Recraft | 图形设计、矢量/品牌视觉 | 后续可扩展 Logo、图标、品牌视觉模板 |

## 4. 产品路线

### 4.1 第一阶段：图库驱动的 MVP

目标：让用户不需要学 prompt，也能从“看到好图”走到“生成自己的图”。

核心页面：

- 首页：瀑布流图片墙 + 搜索框 + 分类入口 + 热门模板。
- 图库页：分类、模型、比例、风格、用途、是否可商用、是否有水印、是否需参考图。
- Prompt 详情页：图片、prompt、参数、来源、授权状态、风险标签、复制、收藏、一键生成。
- 登录页：第三方登录或邮箱/密钥登录。
- 聊天工作台：基于选中 prompt 进入，支持继续改图。
- 历史页：生成记录、收藏、下载、再次编辑。

第一版必须有：

- 图片展示优先，首页不要做成说明文页面。
- 每张图都绑定 prompt、分类、标签、来源、授权状态。
- 未登录可浏览图库；点击生成/收藏/下载高清时要求登录。
- 登录后把 prompt 带入聊天窗口，用户可以继续说“换成春节风格”“保留人物脸”“改成 9:16”。
- 生成失败返还额度，避免用户不信任。

### 4.2 第二阶段：生产力增强

- Prompt 优化器：中文想法转结构化专业 prompt。
- 参考图工作流：上传商品/人像/Logo，生成同款视觉。
- 批量生成：同 prompt 多版本、多尺寸、多模型对比。
- 图片工具：放大、扩图、去背景、换背景、局部重绘。
- 项目/收藏夹：按品牌、客户、商品、活动沉淀素材。
- 公开投稿：用户可把生成作品发布到图库。

### 4.3 第三阶段：商业与团队

- 积分/会员/充值包。
- 邀请奖励和每日免费额度。
- 团队共享额度、角色权限、项目协作。
- API 接入和批量任务。
- 品牌资产库：品牌色、Logo、字体、常用 prompt、禁用词。
- 商用安全检查：人物、商标、敏感词、版权风险提示。

## 5. 首页规划

### 5.1 首屏

首屏目标是“看到图就想点”，而不是解释功能。

结构：

- 顶部导航：Logo、提示词库、AI 生图、价格、登录、开始创作。
- 大标题：发现可复刻的 AI 图片提示词。
- 副标题：精选电商主图、广告海报、人像写真、社媒封面，一键生成同款。
- 搜索框：搜索“香水海报 / 新年头像 / 食品广告 / 3D 手办”。
- 动态瀑布流：展示 20-40 张高质量图，首屏露出下一屏内容。
- CTA：开始创作、浏览图库。

### 5.2 图库卡片字段

- 成品图。
- 标题。
- 分类：电商 / 广告 / 人像 / 海报 / 角色 / UI / 对比。
- 模型：GPT Image 2 / Nano Banana / Seedream / Flux / Ideogram 等。
- 标签：写实、电影感、高级感、产品摄影、竖版、需要参考图。
- 风险标记：疑似品牌/人物/水印/文字。
- 行为：查看提示词、生成同款、收藏。

### 5.3 Prompt 详情页

字段：

- 主图和多张变体。
- Prompt 原文。
- 中文摘要。
- 可替换参数，例如 `{product name}`、`{brand color}`、`{headline text}`。
- 推荐模型、比例、数量、质量。
- 是否需要参考图。
- 来源链接、作者、license。
- 风险提示：商标、真实人物、第三方品牌、疑似水印。
- 按钮：复制 prompt、一键生成、用我的图片生成、收藏。

## 6. 聊天式工作台规划

### 6.1 工作台布局

- 左侧：历史会话、收藏夹、项目。
- 中间：聊天流，展示用户指令、生成结果、失败/排队状态。
- 右侧：生成控制面板。
- 底部：输入框，支持文本、上传参考图、快捷模板、模型切换。

### 6.2 右侧参数

- 模型：自动 / GPT Image / Codex GPT Image / 其他供应商。
- 模式：文生图 / 图生图 / 多图组图 / 局部修改。
- 比例：1:1、3:4、4:5、9:16、16:9。
- 数量：1-4。
- 风格：写实、电商、高级广告、电影感、插画、3D、头像。
- 质量：普通/高清。
- 参考图：上传、删除、排序。
- 输出：保存到项目、是否公开、是否加入图库。

### 6.3 快捷动作

- 优化提示词。
- 生成同款。
- 做 4 个版本。
- 改成小红书封面。
- 改成电商主图。
- 去掉文字。
- 保留人物/商品不变。
- 放大高清。
- 下载。

## 7. 素材与图库采集策略

### 7.1 数据来源分级

| 等级 | 来源 | 可做什么 | 入库策略 |
|---|---|---|---|
| A | 明确开源/CC0 仓库 | 可下载图片和 prompt，作为种子素材 | 入库并标记 license，仍做商标/人物/水印复核 |
| B | 竞品公开图库 | 可研究结构、分类、标题、标签、用户路径 | 只保存 URL、截图证据、结构分析，不直接作为商用图库素材 |
| C | 博客文章 prompt 示例 | 可学习分类、prompt 模板、使用场景 | 摘要归纳，不全文搬运 |
| D | 社区/X/Reddit | 可观察流行趋势 | 保存链接和主题，不直接搬运原图 |
| E | 自生成素材 | 最适合商用 | 用种子 prompt 批量生成无水印、无品牌风险版本 |

### 7.2 已创建采集脚本

脚本位置：

```bash
python3 scripts/collect_image_gallery_seed.py --output data/image-gallery-seed --workers 16
```

输出结构：

```text
data/image-gallery-seed/
├── SUMMARY.json
├── images/
├── records/
│   ├── evolink_cases.json
│   ├── evolink_cases.jsonl
│   └── evolink_cases.csv
└── source_markdown/
```

记录字段：

- `id`
- `case_no`
- `title`
- `category`
- `source_url`
- `source_author`
- `prompt`
- `negative_prompt`
- `image_urls`
- `local_images`
- `license`
- `rights_notes`
- `watermark_status`
- `watermark_signals`
- `tags`
- `dimensions`

水印字段说明：

- `suspected_from_prompt`：prompt 里明确要求 logo、corner logo、watermark 等。
- `not_requested_in_prompt`：prompt 里明确写了 no watermark / no logo。
- `needs_review`：无法自动判断，需要视觉复核。
- `suspected_from_ocr`：可选 OCR 扫描发现疑似文本水印。

可选 OCR：

```bash
python3 scripts/collect_image_gallery_seed.py --output data/image-gallery-seed --workers 16 --ocr-limit 200
```

### 7.3 外部候选池采集进展

当前正式 seed 图库来自 `EvoLinkAI/awesome-gpt-image-2-API-and-Prompts`，优点是 CC0、字段稳定、适合作为低风险启动数据；缺点是审美冲击力偏普通，适合做基础长尾，不适合作为首页宣传主视觉的唯一来源。

为扩大“图片 + prompt”素材池，新增候选池采集脚本：

```bash
python3 scripts/collect_prompt_gallery_candidates.py --source opennana --limit 30 --output data/image-gallery-candidates/opennana --sleep 0.1
```

输出结构：

```text
data/image-gallery-candidates/opennana/
├── SUMMARY.json
├── images/
└── records/
    ├── candidates.json
    ├── candidates.jsonl
    └── candidates.csv
```

2026-06-12 扩池采集结果：

- 来源：OpenNana 公开 prompt gallery 页面与公开前端接口。
- OpenNana：520 条候选记录，518 张记录引用图片；偏人像、热点写真、社媒竖图。
- YouMind GPT Image 2：126 条候选记录，补充 UI、字体、信息图、电商、角色。
- YouMind Nano Banana Pro：129 条候选记录，补充 UI、信息图、3D、建筑、角色、电商。
- PicoTrex Nano Banana：160 条候选记录，补充建筑、3D、信息图、字体、插画、游戏玩法。
- jimmylv Nano Banana：100 条候选记录，补充 3D、UI、字体、角色和玩法案例。
- Indream GPT Image 2：200 条候选记录，补充 UI、字体、信息图、建筑、3D。
- ImgEdify Nano Banana Pro：900 条候选记录，补充人像、产品、风景、动物、抽象背景、建筑、角色。
- jau123 Trending Prompts：900 条候选记录，补充产品、改图、UI、美食、海报、抽象、时尚、社媒封面。
- 合并正式 seed 后，当前 `/api/seed-gallery/facets` 总图库为 3568 条；候选图片目录约 1.2 GB。
- 字段：英文 prompt、中文 prompt、图片 URL、本地图片、作者、来源链接、模型、标签、尺寸、审核状态。
- 审核状态：全部标记为 `candidate_needs_review`，license 为 `unknown`，不可直接作为正式商用图库。

本轮较适合继续精选或复刻生成的方向：

- 2026 世界杯/足球宝贝/球场看台海报：热点明确、竖版传播感强，但部分图存在品牌和队标风险，需要去品牌化重生成。
- iPhone flash / Y2K / luxury beauty portrait：适合首页“人像写真”第一屏，视觉比当前 CC0 seed 更抓眼。
- 棚拍高定女性人像：适合做“写真、杂志封面、时尚头像”模板，但需要避开疑似真人肖像和纹身文字风险。

首批可进入人工精选/复刻的候选 ID：

| 候选 ID | 标题 | 适合展示位 | 上线前处理 |
|---|---|---|---|
| `opennana-15868-world-cup-soccer-girl-stadium-poster` | 足球宝贝赛场看台运动活力商业体育海报 | 热点海报、体育营销模板 | 去品牌 Logo/队标/真实队服元素后重生成 |
| `opennana-15875-sweet-cool-world-cup-soccer-babe-poster` | 甜酷活力世界杯足球宝贝海报 | 热点海报、小红书封面 | 去品牌化，替换为通用赛事视觉 |
| `opennana-15846-cinematic-double-exposure-visual-poster` | 电影感叠影视觉海报生成提示词 | 海报分类、电影感模板 | 核查文字和素材来源，适合做结构复刻 |

人像精选固定清单：

这 6 张用于精选图库“人像写真”分类前置展示，也是首页首屏人像候选。调整分类或排序时，需要保持这些 ID 可搜索、可追踪，并在上线前做肖像、作者授权、平台来源和水印风险复核。

| 候选 ID | 标题 | 适合展示位 | 上线前处理 |
|---|---|---|---|
| `opennana-15839-spring-rural-girl-telephoto-photography` | 春日田园少女长焦摄影真实梦幻感 | 人像首屏、田园清新写真 | 核查肖像/作者授权，复刻生成自有版本 |
| `opennana-15526-highly-realistic-summer-cinematic-portrait-pov` | 高度写实夏日电影感人像第一人称抓拍 | 人像首屏、夏日电影感写真 | 核查肖像和手部细节，复刻生成自有版本 |
| `opennana-15760-outdoor-summer-chinese-girl-fresh-atmosphere-portrait` | 户外夏日中国少女清新氛围写真 | 人像首屏、户外清新写真 | 核查肖像/作者授权，保留自然光和清新氛围 |
| `opennana-15847-soft-light-ccd-summer-energetic-first-love-photo` | 柔光CCD夏日元气初恋感写真 | 人像首屏、CCD 初恋感模板 | 核查肖像/作者授权，保留柔光 CCD 和夏日元气感 |
| `opennana-15540-asian-woman-beach-yoga-sphinx-pose-portrait` | 亚洲女性海滩瑜伽狮身人面像侧颜 | 人像首屏、海滩瑜伽侧颜写真 | 核查姿态尺度、肖像和来源授权，必要时重生成更安全版本 |
| `opennana-15557-high-end-fashion-magazine-portrait-generation` | 高级时尚杂志风格人像大片 | 人像首屏、杂志封面/高级头像模板 | 核查上传参考图和肖像授权，适合做风格迁移模板 |

更大的候选来源：

| 来源 | 规模/状态 | 授权与风险 | 建议用途 |
|---|---|---|---|
| OpenNana | 已采集首批 20 条候选 | 页面公开可访问，但单条版权/作者授权未知 | 候选池、趋势观察、prompt 复刻，不直接上线 |
| MeiGen | 页面有参考价值，程序化访问遇到 Cloudflare 403 | 不绕过反爬；需要授权、手动导出或官方接口 | 研究分类、交互、热门图排序 |
| YouMind-OpenLab/awesome-nano-banana-pro-prompts | README 声称 10,000+ prompts with preview images；GitHub 热度高 | README 有 CC BY 4.0 徽标，但 GitHub API license 显示 NOASSERTION，需要人工核对 | 大规模候选池，保留署名与来源 |
| PicoTrex/Awesome-Nano-Banana-images | GitHub 热度高，README 称来源含 X 和小红书 | GitHub API 与 README 授权信息不完全一致，且社区图片权利复杂 | 只做趋势和 prompt 参考，优先重生成 |

采集边界：

- 不绕过 Cloudflare、登录墙、反爬、付费墙或平台访问控制。
- 对竞品/社区来源，只建立“候选池”和“趋势索引”，不直接进入正式图库。
- 首页宣传图优先使用自生成或明确授权素材；外部好图只作为 prompt 和审美参考。
- 从候选池精选后，应先做品牌/水印/肖像/文字复核，再用自有模型重生成低风险版本。

推荐的宣传图库流水线：

1. 扩池：从公开接口、开源仓库、授权导出中收集图片、prompt、来源、作者、license。
2. 初筛：按视觉冲击力、趋势热度、中文商业价值、可复刻性打分。
3. 风险审核：标记品牌、Logo、水印、真实人物、平台角标、敏感文字。
4. 复刻生成：用候选 prompt 生成自有版本，去掉第三方品牌与疑似肖像。
5. 精选上线：首页只放通过审核或自生成的少量精品，详情页保留 prompt、来源和风险说明。

### 7.4 入库前审核规则

每张图入库前至少标记：

- 授权：CC0 / 自生成 / 竞品参考 / 未知。
- 商标风险：有品牌名、Logo、品牌包装、知名 IP。
- 人物风险：真实名人、疑似真人、肖像参考。
- 水印风险：可见平台水印、角标、作者名、Logo。
- 文字风险：图内文字是否准确、是否含第三方品牌。
- 质量：清晰度、构图、可复刻性、商业价值。

建议首批公开图库只上：

- 无明显第三方品牌。
- 无真实名人。
- 无可见水印。
- prompt 可替换参数清晰。
- 效果适合中文商业场景。

## 8. Prompt 分类体系

建议图库主分类：

- 电商主图
- 广告海报
- 产品摄影
- 人像写真
- 社媒封面
- 角色/IP
- 包装设计
- UI/Mockup
- 3D/手办
- 分镜/故事板
- 节日热点
- 对比改图

二级标签：

- 风格：写实、电影感、高级感、复古、Y2K、日系、韩系、国风、赛博朋克、极简。
- 行业：美妆、食品、服饰、珠宝、家居、数码、汽车、母婴、运动。
- 画幅：1:1、3:4、4:5、9:16、16:9、长图。
- 输入：纯文本、需要参考图、多参考图、商品图、人像图。
- 输出用途：小红书、抖音封面、朋友圈、淘宝、独立站、广告投放、PPT。

## 9. Prompt 模板建议

从 OpenArt、Adobe、LTX 和开源 prompt 案例看，强 prompt 通常包含：

```text
[用途/风格] + [主体] + [构图/镜头] + [环境/道具] + [光线] + [材质/细节] + [文字/品牌要求] + [比例/质量] + [负面约束]
```

产品内可以把复杂 prompt 拆成可编辑表单：

- 主体：商品/人物/场景。
- 风格：高级广告/真实摄影/插画/3D。
- 镜头：正面/俯拍/特写/广角/微距。
- 光线：柔光/金色时刻/棚拍/电影光。
- 背景：纯色/户外/室内/节日/品牌色。
- 文案：标题、副标题、卖点。
- 禁止：水印、Logo、畸形手、错误文字、多余物体。

## 10. 商业化规划

### 10.1 免费层

- 免费浏览图库。
- 每日少量免费生成。
- 低清下载。
- 公开历史。

### 10.2 会员层

- 更多月度积分。
- 高清下载。
- 私密生成。
- 批量生成。
- 更多模型。
- 优先队列。
- 收藏夹和项目数提升。

### 10.3 专业层

- 商业授权提示。
- 团队额度。
- 品牌资产库。
- API。
- 批量商品图。
- 客服支持。

## 11. MVP 排期

### 第 1 周：图库基础

- 建立 seed 数据结构。
- 导入 CC0 开源 prompt 和图片。
- 图库列表、详情页、搜索、分类。
- 水印/版权/风险字段进入后台。

### 第 2 周：生成闭环

- 从详情页一键进入生成。
- 登录后创建会话。
- 生成结果保存历史。
- 失败返还积分。

### 第 3 周：聊天改图

- 支持连续对话改图。
- 支持上传参考图。
- 快捷动作：优化 prompt、同款、变体、改尺寸。
- 支持收藏和再次生成。

### 第 4 周：运营与付费

- 热门榜、新增榜、收藏榜。
- 每日免费额度。
- 邀请奖励。
- 会员价格页。
- 内容审核与后台筛选。

## 12. 关键指标

- 首页图片点击率。
- 图库详情页到登录转化率。
- 登录后首次生成率。
- 首次生成成功率。
- 用户 24 小时内二次生成率。
- prompt 复制率。
- 收藏率。
- 平均每个用户生成张数。
- 失败率和平均等待时间。
- 付费转化率。

## 13. 推荐下一步

1. 完成开源图库 seed 导入，人工挑 100 张“无明显水印、无强品牌风险、效果好”的图作为首页首批。
2. 为每个 prompt 生成中文摘要和可替换参数，降低用户理解成本。
3. 做首页和图库详情页原型，首屏必须用真实素材图。
4. 登录后工作台复用当前项目的图片生成/编辑能力，先把“从图库一键带入 prompt”打通。
5. 后续用自己的服务批量再生成一批无水印、无竞品来源痕迹的原创图，作为正式商业图库主资产。

## 14. Phase 1 Gallery Implementation Notes

Phase 1 has landed the first public inspiration-gallery loop on top of the seed dataset:

- `/gallery` lists public visual prompt cards from the seed gallery before login.
- `/gallery/{id}` shows a MeiGen-style detail page with a large image preview, prompt block, source, tags, watermark/risk labels, and related inspirations.
- Static export now generates 533 concrete seed detail routes from a tracked ID index.
- Copy prompt is available before login.
- Generate Same Style saves a typed gallery intent with `prompt`, `sourceGalleryId`, `sourceKind`, optional `title`, and optional `imageUrl`.
- Unauthenticated users are routed through login with `next` pointing back to `/image`; after login, `/image` consumes the intent once and prefills the image prompt.
- `GET /api/seed-gallery/{id}/related?limit=4` returns deterministic related seed items and excludes the current item.

Verification on 2026-06-12:

- `uv run python -m py_compile api/app.py api/seed_gallery.py services/seed_gallery_service.py` passed.
- `cd web && bun run build` passed and exported the gallery detail routes.
- API smoke checks returned 533 seed items and working related results.
- Browser verification covered desktop and mobile detail layouts, login redirect, prompt prefill, and one-time intent consumption.

### Homepage Gallery Ordering Guardrails

The home page featured gallery is not a purely static category list. The client first reads `/api/seed-gallery/facets`, keeps only categories whose counts are greater than zero, and then applies the hard-coded home ordering. Any change that adds, removes, aggregates, or renames a home category must verify that the backend facets response returns that category.

`portrait` is the first home featured category and has manually curated images that must stay pinned. Do not rely on the first page of `GET /api/seed-gallery?category=portrait&limit=...` to surface those images: `portrait` can also arrive through `category_aliases`, which means product, advertising, or fashion items with a portrait tag can enter the portrait result set. The home page must explicitly fetch the IDs in `homeGalleryCategoryConfigs.portrait.ids`, then use category pagination only as fallback/rotation inventory.

Backend pinned ordering must treat `PINNED_CATEGORY_ITEM_IDS["portrait"]` as cross-subcategory pins. Curated portrait images can derive to `lifestyle-portrait`, `cinematic-portrait`, or another portrait style category, so pinned ranking must not depend on `item.category == "portrait"`.

When facets shape, home category ordering, alias matching, or curated home gallery IDs change, bump `seedGalleryApiCacheVersion` in `web/src/lib/api.ts`. Otherwise browser IndexedDB/localforage can keep returning old facets or old list pages, making local, server, and different browsers appear inconsistent.

Still intentionally deferred:

- User Gallery and My Gallery publishing.
- Share attribution and credit rewards.
- Moderation queues.
- A curated commercial official-gallery set with internally generated, lower-risk images.

## 15. 主要来源

- Magnific: https://www.magnific.com/
- Magnific pricing: https://www.magnific.com/pricing
- Krea: https://www.krea.ai/
- Leonardo: https://leonardo.ai/
- Leonardo pricing: https://leonardo.ai/pricing
- OpenArt: https://openart.ai/
- OpenArt pricing: https://openart.ai/pricing
- Ideogram: https://ideogram.ai/
- MeiGen: https://www.meigen.ai/
- OpenNana: https://opennana.com/awesome-prompt-gallery
- Proxima prompt library: https://proxima.art/prompts
- EvoLinkAI CC0 prompt repo: https://github.com/EvoLinkAI/awesome-gpt-image-2-API-and-Prompts
- YouMind OpenLab Nano Banana Pro prompts: https://github.com/YouMind-OpenLab/awesome-nano-banana-pro-prompts
- PicoTrex Awesome Nano Banana images: https://github.com/PicoTrex/Awesome-Nano-Banana-images
- OpenArt prompt guide: https://openart.ai/blog/best-ai-image-generator-prompts/
- LTX prompt guide: https://ltx.io/blog/ai-image-prompt-guide
- Adobe Firefly prompt examples: https://www.adobe.com/products/firefly/ai-generated-examples/image-prompts.html
- Zapier 2026 AI image generator comparison: https://zapier.com/blog/best-ai-image-generator/
- Tom's Guide 2026 AI image generator comparison: https://www.tomsguide.com/best-picks/best-ai-image-generators
