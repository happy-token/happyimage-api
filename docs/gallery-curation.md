# 精选图库策展指南

代码位置: `services/seed_gallery_service.py`

## 数据来源

| 来源 | 路径 | 说明 |
|:--|:--|:--|
| 种子图库 | `data/image-gallery-seed/` | Docker 镜像内置，首次启动自动复制到 `data/` |
| 候选图库 | `data/image-gallery-candidates/` | 外部采集的大规模图库，需手动同步 |

种子索引文件: `data/image-gallery-seed/records/evolink_cases.json`

## 分类规则

图库分类尽量保持简单稳定，避免被长 prompt 或标签中的局部词带偏：

1. `PINNED_CATEGORY_ITEM_IDS` 中的精选图固定归到对应分类，并在分类内置顶。
2. 标题明确是人像且不是广告、海报、产品、图表等用途时，归到 `portrait`。
3. 其它图片默认按原始来源分类映射到展示分类，例如 `product` -> `product-photography`、`ecommerce` -> `ecommerce-main-image`。
4. 只有原始分类为空、`external` 或 `portrait` 时，才允许用标题关键词做纠偏。
5. 分类筛选只匹配最终展示分类，不再用 tags 或 category aliases 扩大结果。

## 分类展示顺序

由 `DISPLAY_CATEGORY_ORDER` 列表控制。`portrait` 固定排在第一位，其余按此顺序排列。数量来自后端 `/api/seed-gallery/facets` 的实时分类统计，不等同于首页精选图数量。

| 序号 | 分类 | 当前数量 |
|:--|:--|:--|
| 1 | `portrait` | 以 facets 返回为准 |
| 2 | `fashion-editorial` | 1296 |
| 3 | `product-photography` | 266 |
| 4 | `ecommerce-main-image` | 35 |
| 5 | `ad-campaign` | 212 |
| 6 | `poster-design` | 42 |
| 7 | `social-thumbnail` | 233 |
| 8 | `infographic-chart` | 210 |
| 9 | `ui-design` | 56 |
| 10 | `brand-board` | 50 |
| 11 | `logo-typography` | 35 |
| 12 | `food-beverage` | 212 |
| 13 | `storyboard-sequence` | 326 |
| 14 | `editing-workflow` | 4 |
| 15 | `anime-character` | 45 |
| 16 | `character-design` | 9 |
| 17 | `toy-3d` | 75 |
| 18 | `illustration-art` | 36 |
| 19 | `interior-architecture` | 46 |
| 20 | `landscape-nature` | 53 |
| 21 | `abstract-texture` | 60 |
| 22 | `game-visual` | 17 |
| 23 | `animal-pet` | 22 |
| 24 | `external-inspiration` | 50 |

**Portrait 排第一的逻辑**（第 246-247 行）：
```python
def _category_count_sort_key(category: str, count: int):
    if category == "portrait":
        return (0, 0, 0, category)  # 固定第一
    return (1, -count, _category_display_rank(category), category)
```

其他未在 `DISPLAY_CATEGORY_ORDER` 中的分类（如 `sports-poster`、`movie-poster`、`travel-poster`）排在最后，按数量降序。

## 首页精选图片（Portrait）

首页人像区固定展示的精选图由 `PINNED_CATEGORY_ITEM_IDS` 控制顺序。这个列表只控制首页精选和分类内置顶排序，不限制 `portrait` 分类本身的统计和筛选结果。

```
PINNED_CATEGORY_ITEM_IDS = {
    "portrait": [
        "opennana-15839-spring-rural-girl-telephoto-photography",
        "opennana-15526-highly-realistic-summer-cinematic-portrait-pov",
        "opennana-15760-outdoor-summer-chinese-girl-fresh-atmosphere-portrait",
        "opennana-15847-soft-light-ccd-summer-energetic-first-love-photo",
        "opennana-15540-asian-woman-beach-yoga-sphinx-pose-portrait",
        "opennana-15557-high-end-fashion-magazine-portrait-generation",
    ],
}
```

| 顺序 | ID | 标题 | 文件 |
|:--|:--|:--|:--|
| #1 | `opennana-15839-spring-rural-girl-telephoto-photography` | 春日田园少女长焦摄影真实梦幻感 | `opennana/opennana-15839-spring-rural-girl-telephoto-photography-01-83019c1710.jpg` |
| #2 | `opennana-15526-highly-realistic-summer-cinematic-portrait-pov` | 高度写实夏日电影感人像第一人称抓拍 | `opennana/opennana-15526-highly-realistic-summer-cinematic-portrait-pov-01-1e2e049431.jpg` |
| #3 | `opennana-15760-outdoor-summer-chinese-girl-fresh-atmosphere-portrait` | 户外夏日中国少女清新氛围写真 | `opennana/opennana-15760-outdoor-summer-chinese-girl-fresh-atmosphere-portrait-01-01f2e2e93f.jpg` |
| #4 | `opennana-15847-soft-light-ccd-summer-energetic-first-love-photo` | 柔光CCD夏日元气初恋感写真 | `opennana/opennana-15847-soft-light-ccd-summer-energetic-first-love-photo-01-2bc25d957e.jpg` |
| #5 | `opennana-15540-asian-woman-beach-yoga-sphinx-pose-portrait` | 亚洲女性海滩瑜伽狮身人面像侧颜 | `opennana/opennana-15540-asian-woman-beach-yoga-sphinx-pose-portrait-01-9cde9a65f9.jpg` |
| #6 | `opennana-15557-high-end-fashion-magazine-portrait-generation` | 高级时尚杂志风格人像大片 | `opennana/opennana-15557-high-end-fashion-magazine-portrait-generation-01-39590cdef7.jpg` |

## 如何修改精选图片

### 调整顺序

编辑 `services/seed_gallery_service.py` 第 70-77 行，修改 `PINNED_CATEGORY_ITEM_IDS["portrait"]` 数组中的 ID 顺序：

```python
PINNED_CATEGORY_ITEM_IDS = {
    "portrait": [
        "新第一张的id",          # ← 改这里
        "opennana-15839-...",   # 原来的第一张
        ...
    ],
}
```

### 增加新图片

1. 将图片文件放入 `data/image-gallery-candidates/<source>/images/` 目录
2. 在对应 source 的 `records/candidates.json` 中添加条目
3. 在 `PINNED_CATEGORY_ITEM_IDS["portrait"]` 列表中加入新 ID

### 移除图片

从 `PINNED_CATEGORY_ITEM_IDS["portrait"]` 列表中删除对应 ID 即可。图片文件可保留；它不会作为首页精选展示，但仍会按后端推导出的展示分类出现在图库中。

### 调整分类顺序

编辑 `DISPLAY_CATEGORY_ORDER` 列表（第 80 行），调整分类的显示顺序。未列入的分类自动排在最后。

## 图片来源优先级

同一分类内的非置顶图片，按以下优先级排序（第 277-288 行）：

| 优先级 | 来源 | 说明 |
|:--|:--|:--|
| 0 | `opennana` | OpenNana 采集 |
| 1 | `seed` | 内置种子图库 |
| 2 | `youmind` | YouMind 采集 |
| 3 | `indream` | InDream 采集 |
| 4 | `picotrex` | Picotrex 采集 |
| 5 | `jimmylv` | Jimmy LV 采集 |
| 6 | `imgedify` | ImgEdify 采集 |
| 7 | `jau` | JAU 采集 |

同一来源内再按图片数量降序、prompt 长度降序排列。

## 当前完整数据

```
总计: 3,427 张（索引收录）/ 3,617 张（物理文件）
分类: 27 个
来源: 8 个 (seed, opennana, youmind, indream, picotrex, jimmylv, imgedify, jau)
磁盘: ~1.5GB

各来源物理文件:
  seed:             533 张
  opennana:         559 张 (索引 520 条)
  jau-trending:     900 张
  imgedify:         897 张
  indream:          200 张
  picotrex:         160 张
  youmind:          255 张
  jimmylv:           98 张
```
