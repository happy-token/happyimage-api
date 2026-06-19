from __future__ import annotations

import json
import re
from pathlib import Path
from threading import Lock
from typing import Any

from PIL import Image, ImageOps

from services.config import DATA_DIR

SEED_GALLERY_DIR = DATA_DIR / "image-gallery-seed"
SEED_GALLERY_INDEX = SEED_GALLERY_DIR / "records" / "evolink_cases.json"
SEED_GALLERY_IMAGES_DIR = SEED_GALLERY_DIR / "images"
CANDIDATE_GALLERY_DIR = DATA_DIR / "image-gallery-candidates"
THUMBNAIL_WIDTHS = {320, 640, 960}

PUBLIC_TEXT_REMOVE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"https?://\S+",
        r"(?<![A-Za-z0-9])(?:open\s*nana|opennana)(?![A-Za-z0-9])",
        r"(?<![A-Za-z0-9])(?:nano[\s_-]*banana(?:\s*pro)?|nanobanana|nanobanna)(?![A-Za-z0-9])",
        r"(?<![A-Za-z0-9])(?:google\s+)?gemini(?:\s+\d+(?:\.\d+)?)?(?![A-Za-z0-9])",
        r"(?<![A-Za-z0-9])(?:chatgpt[\s_-]*image[\s_-]*2|gpt[\s_-]*image[\s_-]*2)(?![A-Za-z0-9])",
        r"(?<![A-Za-z0-9])(?:midjourney|stable\s*diffusion|dall[\s_-]*e|flux|leonardo\s*ai|hailuo\s*ai|bagel(?:dotcom)?)(?![A-Za-z0-9])",
        r"\b(?:made|created|generated)\s+(?:with|on|using)\b",
        r"\b(?:via|on)\s+(?:x|twitter)\b",
    ]
]

PUBLIC_TEXT_CLEANUP_PATTERNS = [
    (re.compile(r"\bprompt\s*[:：-]\s*", re.IGNORECASE), ""),
    (re.compile(r"\s*[@#]\w+\b"), ""),
    (re.compile(r"\s+([,.;:!?，。；：！？])"), r"\1"),
    (re.compile(r"([（(【\[])\s+"), r"\1"),
    (re.compile(r"\s+([）)】\]])"), r"\1"),
    (re.compile(r"(?:\s*[-–—|/]\s*){2,}"), " - "),
    (re.compile(r"^[\s,.;:!?，。；：！？\-–—|/]+|[\s,.;:!?，。；：！？\-–—|/]+$"), ""),
    (re.compile(r"\s+"), " "),
]

STYLE_CATEGORY_FALLBACKS = {
    "3d-render": "toy-3d",
    "abstract": "abstract-texture",
    "ad-creative": "ad-campaign",
    "animal": "animal-pet",
    "architecture": "interior-architecture",
    "character": "anime-character",
    "comparison": "storyboard-sequence",
    "editing": "editing-workflow",
    "ecommerce": "ecommerce-main-image",
    "external": "external-inspiration",
    "fashion": "fashion-editorial",
    "food": "food-beverage",
    "game": "game-visual",
    "illustration": "illustration-art",
    "infographic": "infographic-chart",
    "landscape": "landscape-nature",
    "portrait": "portrait",
    "poster": "poster-design",
    "product": "product-photography",
    "social-media": "social-thumbnail",
    "typography": "logo-typography",
    "ui": "ui-design",
}

TITLE_CORRECTABLE_SOURCE_CATEGORIES = {
    "",
    "external",
    "portrait",
}

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

DISPLAY_CATEGORY_ORDER = [
    "portrait",
    "fashion-editorial",
    "product-photography",
    "ecommerce-main-image",
    "ad-campaign",
    "poster-design",
    "social-thumbnail",
    "infographic-chart",
    "ui-design",
    "brand-board",
    "logo-typography",
    "food-beverage",
    "storyboard-sequence",
    "editing-workflow",
    "anime-character",
    "character-design",
    "toy-3d",
    "illustration-art",
    "interior-architecture",
    "landscape-nature",
    "abstract-texture",
    "game-visual",
    "animal-pet",
    "external-inspiration",
]

STYLE_CATEGORY_RULES = [
    ("storyboard-sequence", ["storyboard", "shot list", "shots", "panels", "分镜", "故事板"]),
    ("infographic-chart", ["infographic", "diagram", "flowchart", "chart", "timeline", "map", "explainer", "信息图", "流程图", "图表", "地图"]),
    ("ui-design", ["interface", "web design", "dashboard", "landing page", "saas", "界面", "仪表盘"]),
    ("social-thumbnail", ["thumbnail", "youtube", "tiktok", "instagram", "reels", "x post", "social media", "小红书", "封面", "直播"]),
    ("brand-board", ["brand identity", "brand guideline", "mood board", "moodboard", "style guide", "brand system", "品牌", "视觉识别", "情绪板"]),
    ("product-photography", ["product photography", "studio shot", "packaging", "bottle", "skincare", "cosmetic", "perfume", "watch", "headphone", "商品摄影", "产品摄影", "包装"]),
    ("ecommerce-main-image", ["e-commerce", "ecommerce", "main image", "product listing", "商品主图", "电商", "主图"]),
    ("food-beverage", ["food", "drink", "beverage", "restaurant", "cafe", "coffee", "burger", "pizza", "dessert", "美食", "食品", "饮料", "咖啡"]),
    ("ad-campaign", ["advertisement", "campaign", "commercial", "ad poster", "kv", "flyer", "promo", "广告", "营销", "活动"]),
    ("fashion-editorial", ["portrait", "headshot", "selfie", "id photo", "passport photo", "profile photo", "business portrait", "professional headshot", "same person", "identity reference", "couple", "woman", "girl", "man", "boy", "fashion", "outfit", "streetwear", "runway", "lookbook", "editorial", "magazine", "beauty", "makeup", "cinematic portrait", "film still", "35mm", "dslr", "telephoto", "bokeh", "movie still", "人像", "肖像", "写真", "头像", "自拍", "人物", "证件照", "职业头像", "商务头像", "情侣", "女性", "女孩", "男人", "男孩", "穿搭", "时装", "时尚", "大片", "美妆", "妆容", "电影感", "胶片"]),
    ("anime-character", ["anime", "manga", "chibi", "vtuber", "visual novel", "catgirl", "动漫", "漫画", "二次元"]),
    ("character-design", ["character sheet", "character design", "mascot", "persona", "角色设定", "吉祥物"]),
    ("movie-poster", ["movie poster", "film poster", "theatrical", "one-sheet", "电影海报", "剧场"]),
    ("travel-poster", ["travel poster", "travel", "city poster", "postage stamp", "watercolor travel", "旅行", "城市海报", "旅游"]),
    ("sports-poster", ["sports", "soccer", "basketball", "football", "tennis", "athlete", "world cup", "运动", "足球", "篮球", "网球"]),
    ("poster-design", ["poster", "flyer", "key visual", "kv", "海报", "主视觉"]),
    ("logo-typography", ["typography", "type design", "lettering", "font", "wordmark", "calligraphic", "字体", "字母", "标志"]),
    ("animal-pet", ["animal", "creature", "cat", "dog", "bird", "pet", "动物", "生物", "宠物", "猫", "狗"]),
    ("interior-architecture", ["architecture", "interior", "room", "building", "cityscape", "skyline", "furniture", "建筑", "室内", "空间"]),
    ("landscape-nature", ["landscape", "nature", "forest", "mountain", "ocean", "beach", "desert", "valley", "sky", "风景", "自然", "森林", "山", "海", "沙漠"]),
    ("illustration-art", ["illustration", "watercolor", "oil painting", "line art", "sketch", "comic style", "插画", "水彩", "油画", "线稿"]),
    ("toy-3d", ["3d", "render", "figurine", "toy", "doll", "miniature", "isometric", "diorama", "手办", "玩具", "人偶", "微缩", "等距"]),
    ("abstract-texture", ["abstract", "background", "wallpaper", "pattern", "gradient", "texture", "material", "材质", "纹理", "背景", "抽象"]),
    ("game-visual", ["game", "hud", "rpg", "pixel art", "battle screen", "gaming", "游戏", "战斗画面"]),
    ("editing-workflow", ["style transfer", "retexture", "edit", "replace", "remove", "restore", "upscale", "reference image", "uploaded image", "改图", "修复", "替换", "去除", "参考图"]),
]

PORTRAIT_TITLE_NEEDLES = [
    "portrait",
    "headshot",
    "selfie",
    "profile photo",
    "business portrait",
    "professional headshot",
    "woman",
    "girl",
    "man",
    "boy",
    "couple",
    "人像",
    "肖像",
    "写真",
    "头像",
    "自拍",
    "人物",
    "少女",
    "女孩",
    "美女",
    "女性",
    "男人",
    "男孩",
    "情侣",
]

PORTRAIT_TITLE_EXCLUSION_NEEDLES = [
    "ad",
    "advertisement",
    "campaign",
    "commercial",
    "poster",
    "flyer",
    "product",
    "packaging",
    "infographic",
    "diagram",
    "chart",
    "logo",
    "typography",
    "广告",
    "海报",
    "产品",
    "商品",
    "包装",
    "信息图",
    "图表",
    "标志",
    "字体",
    "封面",
]


def _clean(value: object) -> str:
    return str(value or "").strip()


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return min(max(normalized, minimum), maximum)


def _sanitize_public_text(value: object, fallback: str = "") -> str:
    text = _clean(value)
    if not text:
        return fallback
    for marker in (
        '"children":[',
        '"dangerouslySetInnerHTML"',
        "application/ld+json",
        "快速复制",
        "ChatGPT提示词",
        "AI图片提示词",
    ):
        marker_index = text.find(marker)
        if marker_index > 0:
            text = text[:marker_index]
    for pattern in PUBLIC_TEXT_REMOVE_PATTERNS:
        text = pattern.sub(" ", text)
    for pattern, replacement in PUBLIC_TEXT_CLEANUP_PATTERNS:
        text = pattern.sub(replacement, text)
    return text.strip() or fallback


def _dedupe_text_key(value: object) -> str:
    text = _sanitize_public_text(value).lower()
    text = re.sub(r"[\W_]+", "", text, flags=re.UNICODE)
    return text


def _source_name_from_id(item_id: str) -> str:
    if item_id.startswith("opennana-"):
        return "opennana"
    if item_id.startswith("youmind-"):
        return "youmind"
    if item_id.startswith("imgedify-"):
        return "imgedify"
    if item_id.startswith("jau-trending-prompts-"):
        return "jau"
    if item_id.startswith("picotrex-"):
        return "picotrex"
    if item_id.startswith("jimmylv-"):
        return "jimmylv"
    if item_id.startswith("indream-"):
        return "indream"
    return "seed"


def _matches_needle(text: str, needle: str) -> bool:
    if re.fullmatch(r"[a-z0-9][a-z0-9\s-]*[a-z0-9]", needle):
        pattern = rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])"
        return re.search(pattern, text) is not None
    return needle in text


def _matches_any(text: str, needles: list[str]) -> bool:
    return any(_matches_needle(text, needle) for needle in needles)


def _match_style_category(text: str, excluded_categories: set[str] | None = None) -> str:
    excluded = excluded_categories or set()
    for category, needles in STYLE_CATEGORY_RULES:
        if category in excluded:
            continue
        if _matches_any(text, needles):
            return category
    return ""


def _derive_style_category(item_id: object, original_category: object, title: object, prompt: object, tags: list[str]) -> str:
    if _clean(item_id) in PINNED_CATEGORY_ITEM_IDS["portrait"]:
        return "portrait"

    original = re.sub(r"[^a-z0-9]+", "-", _clean(original_category).lower()).strip("-")
    title_text = _clean(title).lower()
    fallback_category = STYLE_CATEGORY_FALLBACKS.get(original, "external-inspiration")
    title_is_portrait = _matches_any(title_text, PORTRAIT_TITLE_NEEDLES) and not _matches_any(
        title_text,
        PORTRAIT_TITLE_EXCLUSION_NEEDLES,
    )

    if title_is_portrait:
        return "portrait"

    if original not in TITLE_CORRECTABLE_SOURCE_CATEGORIES:
        return fallback_category

    title_category = _match_style_category(
        title_text,
        {"fashion-editorial", "infographic-chart", "interior-architecture"},
    )
    if original == "portrait":
        return title_category or "portrait"

    return title_category or fallback_category


def _category_display_rank(category: str) -> int:
    try:
        return DISPLAY_CATEGORY_ORDER.index(category)
    except ValueError:
        return len(DISPLAY_CATEGORY_ORDER)


def _category_count_sort_key(category: str, count: int) -> tuple[int, int, int, str]:
    if category == "portrait":
        return (0, 0, 0, category)
    return (1, -count, _category_display_rank(category), category)


def _pinned_item_rank(item: dict[str, Any]) -> int:
    item_id = _clean(item.get("id"))
    category_pinned_ids = PINNED_CATEGORY_ITEM_IDS.get(_clean(item.get("category")))
    if category_pinned_ids and item_id in category_pinned_ids:
        return category_pinned_ids.index(item_id)
    for pinned_ids in PINNED_CATEGORY_ITEM_IDS.values():
        if item_id in pinned_ids:
            return pinned_ids.index(item_id)
    return 999


def _category_filter_rank(item: dict[str, Any], normalized_category: str) -> int:
    if not normalized_category:
        return 0
    category = _clean(item.get("category")).lower()
    item_id = _clean(item.get("id"))
    if item_id in PINNED_CATEGORY_ITEM_IDS.get(normalized_category, []):
        return 0
    if category == normalized_category:
        return 1
    return 2


def _source_display_rank(item_id: object) -> int:
    source_priority = {
        "opennana": 0,
        "seed": 1,
        "youmind": 2,
        "indream": 3,
        "picotrex": 4,
        "jimmylv": 5,
        "imgedify": 6,
        "jau": 7,
    }
    return source_priority.get(_source_name_from_id(_clean(item_id)), 9)


class SeedGalleryService:
    def __init__(
        self,
        index_file: Path = SEED_GALLERY_INDEX,
        images_dir: Path = SEED_GALLERY_IMAGES_DIR,
        candidate_root: Path = CANDIDATE_GALLERY_DIR,
    ):
        self.index_file = index_file
        self.images_dir = images_dir
        self.candidate_root = candidate_root
        self._lock = Lock()
        self._cache_signature: tuple[tuple[str, float], ...] = ()
        self._cache_items: list[dict[str, Any]] = []

    def _load_items(self) -> list[dict[str, Any]]:
        index_files = self._get_index_files()
        if not index_files:
            return []
        signature = tuple((str(path), path.stat().st_mtime) for path in index_files)
        with self._lock:
            if self._cache_signature == signature:
                return self._cache_items
            normalized = []
            for index_file in index_files:
                try:
                    data = json.loads(index_file.read_text(encoding="utf-8"))
                except Exception:
                    data = []
                source_kind = "candidate" if "image-gallery-candidates" in index_file.parts else "seed"
                items = data if isinstance(data, list) else []
                normalized.extend(
                    self._normalize_item(item, source_kind=source_kind)
                    for item in items
                    if isinstance(item, dict)
                )
            normalized = self._dedupe_items(normalized)
            self._cache_signature = signature
            self._cache_items = normalized
            return normalized

    def _get_index_files(self) -> list[Path]:
        files = []
        if self.candidate_root.exists():
            files.extend(sorted(self.candidate_root.glob("*/records/candidates.json")))
        if self.index_file.exists():
            files.append(self.index_file)
        return files

    def _normalize_item(self, item: dict[str, Any], *, source_kind: str) -> dict[str, Any]:
        local_images = [_clean(path) for path in _as_list(item.get("local_images")) if _clean(path)]
        source_image_urls = [_clean(url).split("?", 1)[0] for url in _as_list(item.get("image_urls")) if _clean(url)]
        dimensions = {
            _clean(dim.get("path")): dim
            for dim in _as_list(item.get("dimensions"))
            if isinstance(dim, dict) and _clean(dim.get("path"))
        }
        images = []
        for path in local_images:
            relative = path.removeprefix("images/").lstrip("/")
            dim = dimensions.get(path) or dimensions.get(f"images/{relative}") or {}
            images.append(
                {
                    "path": path,
                    "url": f"/api/seed-gallery/images/{relative}",
                    "thumbnail_url": f"/api/seed-gallery/thumbnails/640/{relative}",
                    "width": dim.get("width"),
                    "height": dim.get("height"),
                }
            )
        item_id = _clean(item.get("id"))
        title = _sanitize_public_text(item.get("title"), "精选图像参考")
        prompt = _sanitize_public_text(item.get("prompt"))
        negative_prompt = _sanitize_public_text(item.get("negative_prompt"))
        source_author = _sanitize_public_text(item.get("source_author"))
        source_name = _source_name_from_id(item_id)
        original_category = re.sub(r"[^a-z0-9]+", "-", _clean(item.get("category")).lower()).strip("-")
        tags = [
            tag
            for tag in (_sanitize_public_text(value) for value in _as_list(item.get("tags")))
            if tag
        ]
        category = _derive_style_category(item_id, item.get("category"), title, prompt, tags)
        return {
            "id": item_id,
            "case_no": item.get("case_no"),
            "title": title,
            "category": category,
            "category_aliases": [value for value in [original_category, *tags] if value and value != category],
            "source_url": _clean(item.get("source_url")),
            "source_author": source_author,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "license": _clean(item.get("license") or ("unknown" if source_kind == "candidate" else "CC0-1.0")),
            "rights_notes": _clean(item.get("rights_notes")),
            "watermark_status": _clean(item.get("watermark_status") or "needs_review"),
            "watermark_signals": [_clean(value) for value in _as_list(item.get("watermark_signals")) if _clean(value)],
            "tags": tags,
            "images": images,
            "source_repo": "",
            "source_kind": source_kind,
            "review_status": _clean(item.get("review_status")),
            "_source_name": source_name,
            "_source_image_urls": source_image_urls,
            "_dedupe_title_key": _dedupe_text_key(title),
            "_dedupe_prompt_key": _dedupe_text_key(prompt),
        }

    def _dedupe_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sorted_items = sorted(items, key=self._item_priority)
        seen_keys: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for item in sorted_items:
            keys = self._dedupe_keys(item)
            if keys and seen_keys.intersection(keys):
                continue
            seen_keys.update(keys)
            deduped.append({key: value for key, value in item.items() if not key.startswith("_")})
        return deduped

    def _dedupe_keys(self, item: dict[str, Any]) -> set[str]:
        keys = set()
        for image_url in item.get("_source_image_urls") or []:
            if image_url:
                keys.add(f"image:{image_url.lower()}")

        title_key = _clean(item.get("_dedupe_title_key"))
        prompt_key = _clean(item.get("_dedupe_prompt_key"))
        if prompt_key and len(prompt_key) >= 80:
            keys.add(f"prompt:{prompt_key}")
        if title_key and prompt_key and len(title_key) >= 12:
            keys.add(f"title_prompt:{title_key}:{prompt_key[:80]}")
        elif title_key and len(title_key) >= 18:
            keys.add(f"title:{title_key}")
        if not keys:
            item_id = _clean(item.get("id"))
            if item_id:
                keys.add(f"id:{item_id}")
        return keys

    def _item_priority(self, item: dict[str, Any]) -> tuple[int, int, int, str]:
        source_priority = {
            "opennana": 0,
            "seed": 1,
            "youmind": 2,
            "indream": 3,
            "picotrex": 4,
            "jimmylv": 5,
            "imgedify": 6,
            "jau": 7,
        }.get(_clean(item.get("_source_name")), 9)
        image_count = len(item.get("images") or [])
        prompt_length = len(_clean(item.get("prompt")))
        return (source_priority, -image_count, -prompt_length, _clean(item.get("id")))

    def list_items(
        self,
        *,
        query: str = "",
        category: str = "",
        watermark_status: str = "",
        limit: int = 60,
        offset: int = 0,
    ) -> dict[str, Any]:
        items = self._load_items()
        normalized_query = query.strip().lower()
        normalized_category = category.strip().lower()
        normalized_watermark = watermark_status.strip().lower()
        if normalized_category:
            items = [
                item
                for item in items
                if item["category"].lower() == normalized_category
            ]
        if normalized_watermark:
            items = [item for item in items if item["watermark_status"].lower() == normalized_watermark]
        if normalized_query:
            items = [
                item
                for item in items
                if normalized_query in item["title"].lower()
                or normalized_query in item["prompt"].lower()
                or normalized_query in " ".join(item["tags"]).lower()
            ]
        items = sorted(
            items,
            key=lambda item: (
                _category_filter_rank(item, normalized_category),
                self._display_item_priority(item),
            ),
        )
        total = len(items)
        normalized_limit = _clamp_int(limit, 60, 1, 240)
        normalized_offset = _clamp_int(offset, 0, 0, max(total, 0))
        page = items[normalized_offset : normalized_offset + normalized_limit]
        return {
            "items": page,
            "total": total,
            "limit": normalized_limit,
            "offset": normalized_offset,
            "has_more": normalized_offset + normalized_limit < total,
        }

    def related_items(self, case_id: str, limit: int = 4) -> dict[str, Any]:
        normalized_limit = _clamp_int(limit, 4, 1, 12)
        normalized_id = _clean(case_id)
        if not normalized_id:
            return {
                "items": [],
                "total": 0,
                "limit": normalized_limit,
                "offset": 0,
                "has_more": False,
            }

        items = self._load_items()
        current = next((item for item in items if item["id"] == normalized_id), None)
        if current is None:
            return {
                "items": [],
                "total": 0,
                "limit": normalized_limit,
                "offset": 0,
                "has_more": False,
            }

        current_category = current["category"].lower()
        current_tags = {tag.lower() for tag in current["tags"]}
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for index, item in enumerate(items):
            if item["id"] == normalized_id:
                continue
            category_score = 100 if current_category and item["category"].lower() == current_category else 0
            tag_overlap = len(current_tags.intersection(tag.lower() for tag in item["tags"]))
            score = category_score + tag_overlap * 10
            scored.append((score, index, item))

        scored.sort(key=lambda candidate: (-candidate[0], candidate[1]))
        related = [item for _score, _index, item in scored]
        total = len(related)
        return {
            "items": related[:normalized_limit],
            "total": total,
            "limit": normalized_limit,
            "offset": 0,
            "has_more": normalized_limit < total,
        }

    def get_item(self, case_id: str) -> dict[str, Any] | None:
        normalized_id = _clean(case_id)
        if not normalized_id:
            return None
        for item in self._load_items():
            if item["id"] == normalized_id:
                return item
        return None

    def list_image_paths(self) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()
        for item in self._load_items():
            for image in item.get("images") or []:
                path = _clean(image.get("path") if isinstance(image, dict) else "")
                if not path:
                    continue
                relative = path.removeprefix("images/").lstrip("/")
                if relative and relative not in seen:
                    seen.add(relative)
                    paths.append(relative)
        return paths

    def facets(self) -> dict[str, Any]:
        items = self._load_items()
        categories: dict[str, int] = {}
        watermark_statuses: dict[str, int] = {}
        for item in items:
            category = item["category"] or "uncategorized"
            watermark_status = item["watermark_status"] or "needs_review"
            categories[category] = categories.get(category, 0) + 1
            watermark_statuses[watermark_status] = watermark_statuses.get(watermark_status, 0) + 1
        return {
            "total": len(items),
            "categories": dict(sorted(categories.items(), key=lambda entry: _category_count_sort_key(entry[0], entry[1]))),
            "watermark_statuses": watermark_statuses,
            "available": self.index_file.exists(),
            "index_file": str(self.index_file),
        }

    def _display_item_priority(self, item: dict[str, Any]) -> tuple[int, int, int, int, str]:
        image_count = len(item.get("images") or [])
        return (
            _category_display_rank(_clean(item.get("category"))),
            _pinned_item_rank(item),
            _source_display_rank(item.get("id")),
            -image_count,
            _clean(item.get("id")),
        )

    def _resolve_image_file(self, image_path: str) -> tuple[Path, Path] | None:
        clean_path = _clean(image_path).lstrip("/")
        if not clean_path:
            return None
        base_dirs = [self.images_dir]
        if self.candidate_root.exists():
            base_dirs.extend(sorted(self.candidate_root.glob("*/images")))
        for base in base_dirs:
            base_dir = base.resolve()
            candidate = (base_dir / clean_path).resolve()
            try:
                candidate.relative_to(base_dir)
            except ValueError:
                continue
            if candidate.is_file():
                return base_dir, candidate
        return None

    def resolve_image_path(self, image_path: str) -> Path | None:
        resolved = self._resolve_image_file(image_path)
        return resolved[1] if resolved is not None else None

    def get_thumbnail_path(self, width: int, image_path: str) -> Path | None:
        if width not in THUMBNAIL_WIDTHS:
            return None
        resolved = self._resolve_image_file(image_path)
        if resolved is None:
            return None

        base_dir, source_path = resolved
        relative = source_path.relative_to(base_dir)
        return (base_dir.parent / "thumbnails" / f"w{width}" / relative).with_suffix(".webp")

    def resolve_thumbnail_path(self, width: int, image_path: str) -> Path | None:
        if width not in THUMBNAIL_WIDTHS:
            return None
        resolved = self._resolve_image_file(image_path)
        if resolved is None:
            return None

        base_dir, source_path = resolved
        relative = source_path.relative_to(base_dir)
        thumbnail_path = self.get_thumbnail_path(width, image_path)
        if thumbnail_path is None:
            return None
        if thumbnail_path.is_file() and thumbnail_path.stat().st_mtime >= source_path.stat().st_mtime:
            return thumbnail_path

        with self._lock:
            if thumbnail_path.is_file() and thumbnail_path.stat().st_mtime >= source_path.stat().st_mtime:
                return thumbnail_path
            try:
                thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
                with Image.open(source_path) as source:
                    image = ImageOps.exif_transpose(source)
                    if image.mode not in ("RGB", "RGBA"):
                        image = image.convert("RGB")
                    image.thumbnail((width, width * 3), Image.Resampling.LANCZOS)
                    if image.mode == "RGBA":
                        background = Image.new("RGB", image.size, (255, 255, 255))
                        background.paste(image, mask=image.getchannel("A"))
                        image = background
                    image.save(thumbnail_path, format="WEBP", quality=78, method=4)
            except Exception:
                return source_path
        return thumbnail_path


seed_gallery_service = SeedGalleryService()
