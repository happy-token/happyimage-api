#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image


OPENNANA_API = "https://api.opennana.com/api/prompts"
OPENNANA_DETAIL_BASE = "https://opennana.com/awesome-prompt-gallery"
USER_AGENT = "Happy TokenResearchBot/0.2 (+local candidate gallery audit)"
TEXT_TIMEOUT_SECS = 18
IMAGE_TIMEOUT_SECS = 22

GITHUB_MARKDOWN_SOURCES = {
    "youmind-gpt-image-2": {
        "repo": "YouMind-OpenLab/awesome-gpt-image-2",
        "readme": "https://raw.githubusercontent.com/YouMind-OpenLab/awesome-gpt-image-2/main/README.md",
        "base_raw": "https://raw.githubusercontent.com/YouMind-OpenLab/awesome-gpt-image-2/main/",
        "source_home": "https://github.com/YouMind-OpenLab/awesome-gpt-image-2",
        "license": "CC-BY-4.0-unverified",
        "parser": "youmind",
    },
    "youmind-nano-banana-pro": {
        "repo": "YouMind-OpenLab/awesome-nano-banana-pro-prompts",
        "readme": "https://raw.githubusercontent.com/YouMind-OpenLab/awesome-nano-banana-pro-prompts/main/README.md",
        "base_raw": "https://raw.githubusercontent.com/YouMind-OpenLab/awesome-nano-banana-pro-prompts/main/",
        "source_home": "https://github.com/YouMind-OpenLab/awesome-nano-banana-pro-prompts",
        "license": "CC-BY-4.0-unverified",
        "parser": "youmind",
    },
    "picotrex-nano-banana": {
        "repo": "PicoTrex/Awesome-Nano-Banana-images",
        "readme": "https://raw.githubusercontent.com/PicoTrex/Awesome-Nano-Banana-images/main/README.md",
        "base_raw": "https://raw.githubusercontent.com/PicoTrex/Awesome-Nano-Banana-images/main/",
        "source_home": "https://github.com/PicoTrex/Awesome-Nano-Banana-images",
        "license": "CC-BY-4.0-unverified",
        "parser": "case",
    },
    "jimmylv-nano-banana": {
        "repo": "jimmylv/awesome-nano-banana",
        "readme": "https://raw.githubusercontent.com/jimmylv/awesome-nano-banana/main/README.md",
        "base_raw": "https://raw.githubusercontent.com/jimmylv/awesome-nano-banana/main/",
        "source_home": "https://github.com/jimmylv/awesome-nano-banana",
        "license": "CC-BY-4.0-unverified",
        "parser": "case",
    },
    "indream-gpt-image-2": {
        "repo": "indreamai/awesome-gpt-image-2-prompts",
        "readme": "https://raw.githubusercontent.com/indreamai/awesome-gpt-image-2-prompts/main/README.md",
        "base_raw": "https://raw.githubusercontent.com/indreamai/awesome-gpt-image-2-prompts/main/",
        "source_home": "https://github.com/indreamai/awesome-gpt-image-2-prompts",
        "license": "unknown",
        "parser": "indream",
    },
}

GITHUB_JSON_SOURCES = {
    "imgedify-nano-banana-pro": {
        "data": "https://raw.githubusercontent.com/ImgEdify/awesome-nano-banana-pro-prompts/main/data/prompts.json",
        "source_home": "https://github.com/ImgEdify/awesome-nano-banana-pro-prompts",
        "license": "MIT",
        "model": "Nano Banana Pro",
    },
    "jau-trending-prompts": {
        "data": "https://raw.githubusercontent.com/jau123/nanobanana-trending-prompts/main/prompts/prompts.json",
        "source_home": "https://github.com/jau123/nanobanana-trending-prompts",
        "license": "CC-BY-4.0-unverified",
        "model": "Mixed",
    },
}


@dataclass
class CandidateItem:
    id: str
    source: str
    source_id: str
    source_url: str
    source_author: str | None
    title: str
    category: str
    prompt: str
    prompt_zh: str | None
    image_urls: list[str]
    local_images: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    model: str | None = None
    license: str = "unknown"
    rights_notes: str = (
        "Candidate collected from a public prompt gallery for review. Do not publish "
        "or use commercially until source terms, author rights, watermark status, "
        "and likeness/brand risks are reviewed."
    )
    review_status: str = "candidate_needs_review"
    dimensions: list[dict[str, Any]] = field(default_factory=list)


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TEXT_TIMEOUT_SECS) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_json(url: str) -> dict[str, Any]:
    return json.loads(fetch_text(url))


def _clean(value: object) -> str:
    return str(value or "").strip()


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def clean_next_flight(html_text: str) -> str:
    chunks = re.findall(r"self\.__next_f\.push\(\[1,\"([\s\S]*?)\"\]\)</script>", html_text)
    decoded: list[str] = []
    for chunk in chunks:
        try:
            decoded.append(json.loads(f'"{chunk}"'))
        except json.JSONDecodeError:
            decoded.append(chunk.replace(r"\"", '"').replace(r"\n", "\n"))
    return html.unescape("\n".join(decoded))


def extract_text_tokens(flight: str) -> dict[str, str]:
    tokens: dict[str, str] = {}
    matches = list(re.finditer(r"(?m)^([0-9a-z]+):T[0-9a-f]+,", flight))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(flight)
        tokens[match.group(1)] = flight[start:end].strip()
    return tokens


def unescape_jsonish_text(value: str) -> str:
    value = value.replace(r"\/", "/")
    value = value.replace(r"\"", '"')
    value = value.replace("\\\n", "\n")
    value = value.replace(r"\n", "\n")
    value = value.replace(r"\t", "\t")
    return value.strip()


def extract_prompt_objects(flight: str) -> list[dict[str, str]]:
    tokens = extract_text_tokens(flight)
    prompts: list[dict[str, str]] = []
    pattern = re.compile(r'\{"text":"(?P<text>.*?)","type":"(?P<type>[^"]+)"(?:,"label":"(?P<label>[^"]+)")?\}', re.DOTALL)
    for match in pattern.finditer(flight):
        raw_text = match.group("text")
        if raw_text.startswith("$"):
            raw_text = tokens.get(raw_text[1:], raw_text)
        prompts.append(
            {
                "type": match.group("type"),
                "label": match.group("label") or match.group("type"),
                "text": unescape_jsonish_text(raw_text),
            }
        )
    return prompts


def extract_images(flight: str, html_text: str) -> list[str]:
    urls: list[str] = []
    for block in re.findall(r'"images":\[(.*?)\]', flight, flags=re.DOTALL):
        urls.extend(re.findall(r'"(https://img\.opennana\.com/prompts/assets/[^"]+)"', block))
    urls.extend(re.findall(r'<meta property="og:image" content="([^"]+)"', html_text))
    return dedupe([url for url in urls if "/sponsor-" not in url])


def extract_author(flight: str) -> tuple[str | None, str | None]:
    marker = "来源:"
    marker_index = flight.find(marker)
    if marker_index < 0:
        return None, None
    snippet = flight[marker_index : marker_index + 1200]
    href = re.search(r'"href":"([^"]+)"', snippet)
    author = re.search(r'"children":"([^"]+)"', snippet)
    return (author.group(1) if author else None, href.group(1) if href else None)


def extract_model(flight: str) -> str | None:
    match = re.search(r'"children":\["模型: ","([^"]+)"\]', flight)
    return match.group(1) if match else None


def classify(title: str, prompt: str) -> str:
    text = f"{title}\n{prompt}".lower()
    if any(word in text for word in ["style transfer", "retexture", "edit", "replace", "remove", "restore", "upscale", "reference image", "uploaded image", "改图", "修复", "替换", "去除", "参考图"]):
        return "editing"
    if any(word in text for word in ["fashion", "outfit", "streetwear", "runway", "lookbook", "服装", "穿搭", "时装", "时尚"]):
        return "fashion"
    if any(word in text for word in ["social media", "instagram", "x post", "thumbnail", "youtube", "cover", "社媒", "小红书", "封面"]):
        return "social-media"
    if any(word in text for word in ["ui", "ux", "interface", "app", "web design", "dashboard", "界面", "mockup"]):
        return "ui"
    if any(word in text for word in ["infographic", "diagram", "chart", "flowchart", "timeline", "map", "weather card", "信息图", "流程图", "图表", "地图", "卡片"]):
        return "infographic"
    if any(word in text for word in ["logo", "typography", "type design", "lettering", "font", "wordmark", "字体", "字母", "标志"]):
        return "typography"
    if any(word in text for word in ["architecture", "interior", "room", "building", "cityscape", "skyline", "城市", "建筑", "室内", "空间"]):
        return "architecture"
    if any(word in text for word in ["landscape", "nature", "forest", "mountain", "ocean", "beach", "desert", "valley", "sky", "风景", "自然", "森林", "山", "海", "沙漠"]):
        return "landscape"
    if any(word in text for word in ["abstract", "background", "wallpaper", "pattern", "gradient", "texture", "material", "材质", "纹理", "背景", "抽象"]):
        return "abstract"
    if any(word in text for word in ["animal", "creature", "cat", "dog", "bird", "pet", "动物", "宠物", "猫", "狗"]):
        return "animal"
    if any(word in text for word in ["sports", "soccer", "basketball", "football", "tennis", "athlete", "运动", "足球", "篮球"]):
        return "sports"
    if any(word in text for word in ["food", "drink", "beverage", "restaurant", "cafe", "coffee", "burger", "pizza", "美食", "食品", "饮料", "咖啡"]):
        return "food"
    if any(word in text for word in ["game", "hud", "rpg", "pixel art", "battle screen", "游戏", "战斗画面"]):
        return "game"
    if any(word in text for word in ["3d", "render", "figurine", "toy", "miniature", "isometric", "手办", "玩具", "微缩", "等距"]):
        return "3d-render"
    if any(word in text for word in ["anime", "manga", "character", "chibi", "mascot", "comic", "storyboard", "角色", "漫画", "分镜", "吉祥物"]):
        return "character"
    if any(word in text for word in ["product", "e-commerce", "商品", "电商", "主图"]):
        return "product"
    if any(word in text for word in ["poster", "海报", "kv", "campaign", "广告"]):
        return "poster"
    if any(word in text for word in ["woman", "girl", "female", "beauty", "portrait", "selfie", "avatar", "fashion editorial", "写真", "美女", "人像", "少女"]):
        return "portrait"
    if any(word in text for word in ["illustration", "watercolor", "oil painting", "line art", "sketch", "插画", "水彩", "油画", "线稿"]):
        return "illustration"
    return "external"


def normalize_category(value: object, title: str, prompt: str) -> str:
    raw = str(value or "").strip().lower()
    if raw:
        normalized = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
        direct = {
            "portrait": "portrait",
            "profile-avatar": "portrait",
            "avatar-profile": "portrait",
            "landscape": "landscape",
            "nature": "landscape",
            "product": "product",
            "product-brand": "product",
            "product-marketing": "product",
            "e-commerce-main-image": "ecommerce",
            "ecommerce-main-image": "ecommerce",
            "character": "character",
            "character-design": "character",
            "anime-manga": "character",
            "abstract": "abstract",
            "background": "abstract",
            "wallpaper-background": "abstract",
            "food": "food",
            "food-drink": "food",
            "architecture": "architecture",
            "architecture-interior": "architecture",
            "animal": "animal",
            "animal-creature": "animal",
            "ui-graphic": "ui",
            "app-web-design": "ui",
            "social-media-creative": "social-media",
            "social-media-post": "social-media",
            "poster-design": "poster",
            "poster-flyer": "poster",
            "ad-poster": "poster",
            "brand-marketing": "typography",
            "infographic-communication": "infographic",
            "infographic-edu-visual": "infographic",
            "diagram-chart": "infographic",
            "3d-render": "3d-render",
            "game-asset": "game",
        }
        if normalized in direct:
            return direct[normalized]
    return classify(title, prompt)


def infer_tags(title: str, prompt: str) -> list[str]:
    text = f"{title}\n{prompt}".lower()
    rules = {
        "trend-2026-world-cup": ["world cup", "世界杯", "soccer", "football stadium", "足球"],
        "female-portrait": ["woman", "female", "girl", "beauty", "美女", "女性", "少女"],
        "flash-photo": ["flash", "闪光灯", "iphone"],
        "fashion": ["fashion", "时尚", "editorial", "社论"],
        "poster": ["poster", "海报"],
        "commercial": ["commercial", "campaign", "商业", "广告"],
        "sexy-non-explicit": ["sexy", "性感", "微性感", "bikini"],
        "architecture": ["architecture", "interior", "建筑", "室内"],
        "infographic": ["infographic", "diagram", "chart", "信息图", "流程图"],
        "3d-render": ["3d", "render", "figurine", "toy", "手办", "玩具"],
        "typography": ["typography", "logo", "lettering", "字体", "字母"],
        "food-drink": ["food", "drink", "beverage", "美食", "饮料"],
        "landscape": ["landscape", "nature", "mountain", "forest", "风景", "自然"],
        "abstract": ["abstract", "background", "pattern", "texture", "抽象", "背景", "纹理"],
        "animal": ["animal", "pet", "cat", "dog", "动物", "宠物"],
        "editing": ["style transfer", "edit", "reference image", "改图", "参考图"],
        "social-media": ["social media", "instagram", "thumbnail", "小红书", "封面"],
        "sports": ["sports", "soccer", "basketball", "运动", "足球", "篮球"],
    }
    return sorted(tag for tag, needles in rules.items() if any(needle in text for needle in needles))


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value).strip("-")
    return value[:80] or "candidate"


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


def filename_for(url: str, candidate_id: str, index: int) -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix or ".jpg"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"{candidate_id}-{index + 1:02d}-{digest}{suffix.lower()}"


def download_file(url: str, destination: Path) -> bool:
    if destination.exists() and destination.stat().st_size > 0:
        return True
    destination.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=IMAGE_TIMEOUT_SECS) as resp:
            data = resp.read()
        tmp = destination.with_suffix(destination.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(destination)
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def add_dimensions(item: CandidateItem, output_dir: Path) -> None:
    dimensions: list[dict[str, Any]] = []
    for rel in item.local_images:
        try:
            with Image.open(output_dir / rel) as image:
                dimensions.append({"path": rel, "width": image.width, "height": image.height})
        except OSError:
            dimensions.append({"path": rel, "error": "unreadable"})
    item.dimensions = dimensions


def collect_opennana(limit: int, sleep_secs: float, max_pages: int) -> list[CandidateItem]:
    candidates: list[CandidateItem] = []
    seen_ids: set[str] = set()
    page = 1
    has_more = True
    while has_more:
        if max_pages > 0 and page > max_pages:
            break
        if limit > 0 and len(candidates) >= limit:
            break

        url = f"{OPENNANA_API}?media_type=image&page={page}&page_size=20"
        payload = fetch_json(url)
        data = payload.get("data", {})
        items = data.get("items", [])
        if not items:
            break

        page_candidates = collect_opennana_page(items, sleep_secs, seen_ids, limit - len(candidates) if limit > 0 else 0)
        candidates.extend(page_candidates)
        print(
            f"scanned page {page}, added {len(page_candidates)}, kept {len(candidates)}",
            flush=True,
        )

        pagination = data.get("pagination") if isinstance(data, dict) else {}
        has_more = bool(pagination.get("has_more")) if isinstance(pagination, dict) else False
        page += 1

    return candidates


def collect_opennana_page(
    items: list[dict[str, Any]],
    sleep_secs: float,
    seen_ids: set[str],
    remaining_limit: int,
) -> list[CandidateItem]:
    candidates: list[CandidateItem] = []
    for item in items:
        if remaining_limit > 0 and len(candidates) >= remaining_limit:
            break
        source_id = str(item.get("id"))
        if source_id in seen_ids:
            continue
        seen_ids.add(source_id)
        slug = item.get("slug") or str(item.get("id"))
        title = item.get("title") or slug
        detail_url = f"{OPENNANA_DETAIL_BASE}/{slug}"
        try:
            html_text = fetch_text(detail_url)
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
        flight = clean_next_flight(html_text)
        prompt_objects = extract_prompt_objects(flight)
        prompt_en = next((prompt["text"] for prompt in prompt_objects if prompt["type"] == "en"), "")
        prompt_zh = next((prompt["text"] for prompt in prompt_objects if prompt["type"] == "zh"), None)
        prompt = prompt_en or prompt_zh or ""
        image_urls = extract_images(flight, html_text) or [item.get("cover_image", "")]
        image_urls = [url for url in image_urls if url]
        if not prompt or not image_urls:
            continue
        author, source_url = extract_author(flight)
        candidate_id = f"opennana-{item.get('id')}-{slugify(slug)}"
        category = classify(title, prompt)
        candidates.append(
            CandidateItem(
                id=candidate_id,
                source="opennana",
                source_id=source_id,
                source_url=source_url or detail_url,
                source_author=author,
                title=title,
                category=category,
                prompt=prompt,
                prompt_zh=prompt_zh,
                image_urls=image_urls,
                tags=infer_tags(title, prompt),
                model=extract_model(flight),
            )
        )
        if sleep_secs > 0:
            time.sleep(sleep_secs)
    return candidates


def resolve_markdown_url(value: str, base_raw: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return urllib.parse.urljoin(base_raw, value.removeprefix("./"))


def markdown_links(text: str) -> list[tuple[str, str]]:
    links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', text)
    links.extend((alt, src) for src, alt in re.findall(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*alt=["\']([^"\']*)["\']', text))
    return links


def strip_markdown(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"[*_`>#|]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def first_fenced_code(block: str) -> str:
    match = re.search(r"```(?:[a-zA-Z0-9_-]+)?\n([\s\S]*?)```", block)
    return match.group(1).strip() if match else ""


def extract_img_srcs(block: str, base_raw: str) -> list[str]:
    urls = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', block)
    urls.extend(re.findall(r'!\[[^\]]*\]\(([^)]+)\)', block))
    return dedupe([resolve_markdown_url(url.split()[0], base_raw) for url in urls if not url.startswith("https://img.shields.io")])


def extract_source_author(block: str) -> tuple[str | None, str | None]:
    author_match = re.search(r"\*\*Author:\*\*\s*\[([^\]]+)\]\(([^)]+)\)", block)
    if author_match:
        return author_match.group(1), author_match.group(2)
    by_match = re.search(r"\(by\s+\[?(@?[^)\]]+)\]?\(([^)]+)\)\)", block)
    if by_match:
        return by_match.group(1), by_match.group(2)
    by_match = re.search(r"^## by \[([^\]]+)\]\(<([^>]+)>", block)
    if by_match:
        return by_match.group(1), by_match.group(2)
    return None, None


def extract_source_url(block: str, fallback: str) -> str:
    for pattern in [
        r"\*\*Source:\*\*\s*\[[^\]]+\]\(([^)]+)\)",
        r"\[Source Link\]\(([^)]+)\)",
        r"\[Try Now\]\(([^)]+)\)",
        r"\*\*\[👉 Try it now →\]\(([^)]+)\)\*\*",
    ]:
        match = re.search(pattern, block)
        if match:
            return match.group(1)
    return fallback


def collect_github_markdown(source: str, limit: int) -> list[CandidateItem]:
    config = GITHUB_MARKDOWN_SOURCES[source]
    markdown = fetch_text(str(config["readme"]))
    parser = str(config["parser"])
    if parser == "youmind":
        return parse_youminds_markdown(source, markdown, config, limit)
    if parser == "indream":
        return parse_indream_markdown(source, markdown, config, limit)
    return parse_case_markdown(source, markdown, config, limit)


def collect_github_json(source: str, limit: int) -> list[CandidateItem]:
    config = GITHUB_JSON_SOURCES[source]
    payload = fetch_json(str(config["data"]))
    rows = payload if isinstance(payload, list) else payload.get("prompts", [])
    candidates: list[CandidateItem] = []
    for index, row in enumerate(rows, start=1):
        if limit > 0 and len(candidates) >= limit:
            break
        if not isinstance(row, dict):
            continue
        prompt = _clean(row.get("prompt"))
        image_urls = [_clean(url) for url in _as_list(row.get("images")) if _clean(url)]
        image = _clean(row.get("image"))
        if image:
            image_urls.insert(0, image)
        image_urls = dedupe([url for url in image_urls if url.startswith(("http://", "https://"))])
        if not prompt or not image_urls:
            continue
        source_id = _clean(row.get("id") or row.get("rank") or index)
        title = _clean(row.get("title")) or f"{source} prompt {source_id}"
        raw_category = row.get("category")
        if raw_category is None and _as_list(row.get("categories")):
            raw_category = _as_list(row.get("categories"))[0]
        tags = [_clean(tag) for tag in _as_list(row.get("tags")) if _clean(tag)]
        style = _clean(row.get("style"))
        if style:
            tags.append(style)
        candidate_id = f"{source}-{source_id}-{slugify(title)}"
        candidates.append(
            CandidateItem(
                id=candidate_id,
                source=source,
                source_id=source_id,
                source_url=_clean(row.get("source_url")) or str(config["source_home"]),
                source_author=_clean(row.get("author") or row.get("author_name")) or None,
                title=title,
                category=normalize_category(raw_category, title, prompt),
                prompt=prompt,
                prompt_zh=prompt if re.search(r"[\u4e00-\u9fff]", prompt) else None,
                image_urls=image_urls,
                tags=dedupe([*tags, *infer_tags(title, prompt)]),
                model=_clean(row.get("model")) or str(config["model"]),
                license=str(config["license"]),
            )
        )
    return candidates


def parse_youminds_markdown(source: str, markdown: str, config: dict[str, str], limit: int) -> list[CandidateItem]:
    parts = re.split(r"(?=^### No\. \d+: )", markdown, flags=re.MULTILINE)
    candidates: list[CandidateItem] = []
    for block in parts:
        if limit > 0 and len(candidates) >= limit:
            break
        title_match = re.match(r"### No\. (?P<num>\d+): (?P<title>.+)", block)
        if not title_match:
            continue
        prompt = first_fenced_code(block)
        image_urls = extract_img_srcs(block, str(config["base_raw"]))
        if not prompt or not image_urls:
            continue
        number = title_match.group("num")
        title = strip_markdown(title_match.group("title"))
        author, author_url = extract_source_author(block)
        source_url = extract_source_url(block, author_url or str(config["source_home"]))
        candidate_id = f"{source}-{number}-{slugify(title)}"
        candidates.append(
            CandidateItem(
                id=candidate_id,
                source=source,
                source_id=number,
                source_url=source_url,
                source_author=author,
                title=title,
                category=normalize_category(None, title, prompt),
                prompt=prompt,
                prompt_zh=None,
                image_urls=image_urls,
                tags=infer_tags(title, prompt),
                model="GPT Image 2" if "gpt" in source else "Nano Banana Pro",
                license=str(config["license"]),
            )
        )
    return candidates


def parse_case_markdown(source: str, markdown: str, config: dict[str, str], limit: int) -> list[CandidateItem]:
    parts = re.split(r"(?=^### (?:Case|例)\s*\d+[:：])", markdown, flags=re.MULTILINE)
    candidates: list[CandidateItem] = []
    for block in parts:
        if limit > 0 and len(candidates) >= limit:
            break
        title_match = re.match(r"### (?P<label>(?:Case|例)\s*(?P<num>\d+)[:：]\s*(?P<title>.+))", block)
        if not title_match:
            continue
        prompt = first_fenced_code(block)
        image_urls = extract_img_srcs(block, str(config["base_raw"]))
        if not prompt or not image_urls:
            continue
        number = title_match.group("num")
        title = strip_markdown(title_match.group("title"))
        author, author_url = extract_source_author(block)
        source_url = extract_source_url(block, author_url or str(config["source_home"]))
        candidate_id = f"{source}-{number}-{slugify(title)}"
        candidates.append(
            CandidateItem(
                id=candidate_id,
                source=source,
                source_id=number,
                source_url=source_url,
                source_author=author,
                title=title,
                category=normalize_category(None, title, prompt),
                prompt=prompt,
                prompt_zh=prompt if re.search(r"[\u4e00-\u9fff]", prompt) else None,
                image_urls=image_urls,
                tags=infer_tags(title, prompt),
                model="Nano Banana / Gemini",
                license=str(config["license"]),
            )
        )
    return candidates


def parse_indream_markdown(source: str, markdown: str, config: dict[str, str], limit: int) -> list[CandidateItem]:
    parts = re.split(r"(?=^## by \[)", markdown, flags=re.MULTILINE)
    candidates: list[CandidateItem] = []
    for index, block in enumerate(parts, start=1):
        if limit > 0 and len(candidates) >= limit:
            break
        if not block.startswith("## by ["):
            continue
        prompt = first_fenced_code(block)
        image_urls = extract_img_srcs(block, str(config["base_raw"]))
        if not prompt or not image_urls:
            continue
        author, author_url = extract_source_author(block)
        source_url = extract_source_url(block, author_url or str(config["source_home"]))
        source_id_match = re.search(r"modelPromptId=([a-z0-9-]+)", block)
        source_id = source_id_match.group(1) if source_id_match else str(index)
        title_seed = prompt.splitlines()[0][:80] if prompt else f"Prompt {index}"
        title = f"GPT Image 2 - {strip_markdown(title_seed)}"
        candidate_id = f"{source}-{source_id[:12]}-{slugify(title)}"
        candidates.append(
            CandidateItem(
                id=candidate_id,
                source=source,
                source_id=source_id,
                source_url=source_url,
                source_author=author,
                title=title,
                category=normalize_category(None, title, prompt),
                prompt=prompt,
                prompt_zh=prompt if re.search(r"[\u4e00-\u9fff]", prompt) else None,
                image_urls=image_urls,
                tags=infer_tags(title, prompt),
                model="GPT Image 2",
                license=str(config["license"]),
            )
        )
    return candidates


def write_outputs(
    candidates: list[CandidateItem],
    output_dir: Path,
    download: bool,
    image_limit_per_item: int,
    download_workers: int,
) -> None:
    records_dir = output_dir / "records"
    images_dir = output_dir / "images"
    records_dir.mkdir(parents=True, exist_ok=True)
    for item in candidates:
        image_urls = item.image_urls[:image_limit_per_item] if image_limit_per_item > 0 else item.image_urls
        item.image_urls = image_urls
        item.local_images = [
            str(Path("images") / filename_for(url, item.id, index))
            for index, url in enumerate(image_urls)
        ]

    if download:
        download_images(candidates, output_dir, download_workers)
        for item in candidates:
            add_dimensions(item, output_dir)

    rows = [asdict(item) for item in candidates]

    (records_dir / "candidates.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with (records_dir / "candidates.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (records_dir / "candidates.csv").open("w", encoding="utf-8", newline="") as handle:
        fieldnames = ["id", "source", "source_id", "title", "category", "source_url", "source_author", "model", "tags", "local_images", "prompt"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in candidates:
            writer.writerow({
                "id": item.id,
                "source": item.source,
                "source_id": item.source_id,
                "title": item.title,
                "category": item.category,
                "source_url": item.source_url,
                "source_author": item.source_author or "",
                "model": item.model or "",
                "tags": "|".join(item.tags),
                "local_images": "|".join(item.local_images),
                "prompt": item.prompt.replace("\n", "\\n"),
            })
    summary = {
        "candidate_count": len(candidates),
        "image_count": sum(len(item.local_images) for item in candidates),
        "sources": sorted({item.source for item in candidates}),
        "categories": {
            category: sum(1 for item in candidates if item.category == category)
            for category in sorted({item.category for item in candidates})
        },
        "downloaded": download,
        "notes": [
            "This is a review pool, not the production seed gallery.",
            "OpenNana items are public gallery records; rights/license remain unknown until reviewed.",
            "Cloudflare or other anti-bot protections are not bypassed.",
        ],
    }
    (output_dir / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def download_images(candidates: list[CandidateItem], output_dir: Path, workers: int) -> None:
    jobs: list[tuple[CandidateItem, str, str]] = []
    for item in candidates:
        jobs.extend((item, url, rel) for url, rel in zip(item.image_urls, item.local_images))
    if not jobs:
        return

    ok_by_id: dict[str, list[tuple[str, str]]] = {item.id: [] for item in candidates}
    normalized_workers = max(1, workers)
    completed = 0
    with ThreadPoolExecutor(max_workers=normalized_workers) as executor:
        future_map = {
            executor.submit(download_file, url, output_dir / rel): (item, url, rel)
            for item, url, rel in jobs
        }
        for future in as_completed(future_map):
            item, url, rel = future_map[future]
            ok = False
            try:
                ok = future.result()
            except Exception:
                ok = False
            if ok:
                ok_by_id[item.id].append((url, rel))
            completed += 1
            if completed % 50 == 0 or completed == len(jobs):
                print(f"downloaded {completed}/{len(jobs)} images", flush=True)

    for item in candidates:
        ok_pairs = ok_by_id.get(item.id, [])
        item.image_urls = [url for url, _rel in ok_pairs]
        item.local_images = [rel for _url, rel in ok_pairs]


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect external prompt gallery candidates for review.")
    parser.add_argument("--source", choices=["opennana", *GITHUB_MARKDOWN_SOURCES.keys(), *GITHUB_JSON_SOURCES.keys()], default="opennana")
    parser.add_argument("--limit", type=int, default=120, help="Maximum candidates to keep; 0 means crawl until max-pages/API end")
    parser.add_argument("--max-pages", type=int, default=20, help="Maximum OpenNana list pages to scan; 0 means no page cap")
    parser.add_argument("--output", default="data/image-gallery-candidates/opennana")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--image-limit-per-item", type=int, default=2, help="Maximum images to download per prompt; 0 means no cap")
    parser.add_argument("--download-workers", type=int, default=8)
    parser.add_argument("--sleep", type=float, default=0.15, help="Polite delay between detail page requests")
    args = parser.parse_args()

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.source == "opennana":
        candidates = collect_opennana(limit=args.limit, sleep_secs=args.sleep, max_pages=args.max_pages)
    elif args.source in GITHUB_JSON_SOURCES:
        candidates = collect_github_json(args.source, limit=args.limit)
        print(f"collected {len(candidates)} candidates from {args.source}", flush=True)
    else:
        candidates = collect_github_markdown(args.source, limit=args.limit)
        print(f"collected {len(candidates)} candidates from {args.source}", flush=True)
    write_outputs(
        candidates,
        output_dir,
        download=not args.skip_download,
        image_limit_per_item=args.image_limit_per_item,
        download_workers=args.download_workers,
    )
    print((output_dir / "SUMMARY.json").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
