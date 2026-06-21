#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from PIL import Image


REPO = "EvoLinkAI/awesome-gpt-image-2-API-and-Prompts"
BRANCH = "main"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"
CATEGORY_FILES = {
    "ecommerce": "cases/ecommerce.md",
    "ad-creative": "cases/ad-creative.md",
    "portrait": "cases/portrait.md",
    "poster": "cases/poster.md",
    "character": "cases/character.md",
    "ui": "cases/ui.md",
    "comparison": "cases/comparison.md",
}


CASE_RE = re.compile(
    r"^###\s+Case\s+(?P<case_no>\d+):\s+\[(?P<title>[^\]]+)\]\((?P<source_url>[^)]+)\)"
    r"(?:\s+\(by\s+(?P<author>.+?)\))?\s*$",
    re.MULTILINE,
)
IMG_RE = re.compile(r"<img\s+[^>]*src=[\"'](?P<src>[^\"']+)[\"'][^>]*>", re.IGNORECASE)
ALT_RE = re.compile(r"alt=[\"'](?P<alt>[^\"']*)[\"']", re.IGNORECASE)
CODE_RE = re.compile(r"\*\*Prompt:\*\*\s*```(?P<prompt>.*?)```", re.DOTALL)
NEGATIVE_RE = re.compile(r"Negative Prompt:\s*```(?P<negative>.*?)```", re.DOTALL | re.IGNORECASE)


@dataclass
class GalleryCase:
    id: str
    case_no: int
    title: str
    category: str
    source_url: str
    source_author: str | None
    prompt: str
    negative_prompt: str | None
    image_urls: list[str]
    image_alts: list[str]
    local_images: list[str] = field(default_factory=list)
    license: str = "CC0-1.0"
    source_repo: str = f"https://github.com/{REPO}"
    rights_notes: str = (
        "Repository is CC0-1.0, but prompts/images may depict brands, people, "
        "logos, or third-party source material. Review before commercial use."
    )
    watermark_status: str = "needs_review"
    watermark_signals: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    dimensions: list[dict] = field(default_factory=list)


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "HappyImageResearchBot/0.1"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8")


def extract_author(raw: str | None) -> str | None:
    if not raw:
        return None
    match = re.search(r"\[@?([^\]]+)\]", raw)
    if match:
        return match.group(1).strip()
    text = re.sub(r"\[|\]|\(|\)|https?://\S+", "", raw).strip()
    return text or None


def normalise_prompt(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text.strip())


def parse_cases(category: str, markdown: str) -> list[GalleryCase]:
    matches = list(CASE_RE.finditer(markdown))
    cases: list[GalleryCase] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        block = markdown[start:end]
        prompt_match = CODE_RE.search(block)
        if not prompt_match:
            continue
        image_urls: list[str] = []
        image_alts: list[str] = []
        for img_match in IMG_RE.finditer(block):
            tag = img_match.group(0)
            src = img_match.group("src")
            if src.startswith("https://raw.githubusercontent.com/") and "/images/" in src:
                image_urls.append(src)
                alt_match = ALT_RE.search(tag)
                image_alts.append(alt_match.group("alt") if alt_match else "")
        if not image_urls:
            continue
        case_no = int(match.group("case_no"))
        slug = slugify(match.group("title"))
        negative = NEGATIVE_RE.search(block)
        cases.append(
            GalleryCase(
                id=f"{category}-{case_no}-{slug}",
                case_no=case_no,
                title=match.group("title").strip(),
                category=category,
                source_url=match.group("source_url").strip(),
                source_author=extract_author(match.group("author")),
                prompt=normalise_prompt(prompt_match.group("prompt")),
                negative_prompt=normalise_prompt(negative.group("negative")) if negative else None,
                image_urls=dedupe(image_urls),
                image_alts=image_alts,
            )
        )
    return cases


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:80] or "case"


def dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def filename_for(url: str, case_id: str, index: int) -> str:
    suffix = Path(url.split("?", 1)[0]).suffix or ".jpg"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"{case_id}-{index + 1:02d}-{digest}{suffix.lower()}"


def download_one(args: tuple[str, Path]) -> tuple[str, bool, str | None]:
    url, dest = args
    if dest.exists() and dest.stat().st_size > 0:
        return str(dest), True, None
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "HappyImageResearchBot/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)
        return str(dest), True, None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return str(dest), False, str(exc)


def add_dimensions(case: GalleryCase, output_dir: Path) -> None:
    dims = []
    for rel in case.local_images:
        path = output_dir / rel
        try:
            with Image.open(path) as image:
                dims.append({"path": rel, "width": image.width, "height": image.height})
        except OSError:
            dims.append({"path": rel, "error": "unreadable"})
    case.dimensions = dims


def infer_tags(case: GalleryCase) -> list[str]:
    text = f"{case.title}\n{case.prompt}".lower()
    rules = {
        "product": ["product", "e-commerce", "commercial", "packaging", "bottle", "poster"],
        "portrait": ["portrait", "woman", "man", "model", "face", "headshot"],
        "advertising": ["advertisement", "ad ", "campaign", "brand", "poster"],
        "typography": ["text", "headline", "logo", "typography", "label"],
        "reference-image": ["uploaded image", "reference image", "provided reference"],
        "storyboard": ["storyboard", "panel", "scene", "shot list"],
        "social": ["instagram", "tiktok", "reels", "social"],
        "watermark-risk": ["watermark", "logo", "brand logo", "corner logo", "pollo.ai"],
    }
    tags = [tag for tag, needles in rules.items() if any(needle in text for needle in needles)]
    return sorted(set([case.category, *tags]))


def infer_watermark(case: GalleryCase) -> tuple[str, list[str]]:
    text = f"{case.title}\n{case.prompt}\n{case.negative_prompt or ''}".lower()
    signals: list[str] = []
    positive_needles = [
        "watermark",
        "corner logo",
        "brand logo",
        "small white logo",
        "logo in the top",
        "pollo.ai",
    ]
    negative_needles = [
        "no watermark",
        "no logos",
        "no logo",
        "without watermark",
        "avoid watermark",
    ]
    for needle in positive_needles:
        if needle in text:
            signals.append(f"prompt_mentions:{needle}")
    for needle in negative_needles:
        if needle in text:
            signals.append(f"prompt_negates:{needle}")
    if any(signal.startswith("prompt_mentions:") for signal in signals):
        return "suspected_from_prompt", signals
    if any(signal.startswith("prompt_negates:") for signal in signals):
        return "not_requested_in_prompt", signals
    return "needs_review", signals


def run_ocr(path: Path) -> str:
    if not shutil.which("tesseract"):
        return ""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir) / "ocr.png"
        try:
            with Image.open(path) as img:
                img.thumbnail((1400, 1400))
                img.convert("RGB").save(tmp)
            proc = subprocess.run(
                ["tesseract", str(tmp), "stdout", "-l", "eng"],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            return proc.stdout.strip()
        except Exception:
            return ""


def maybe_ocr_cases(cases: list[GalleryCase], output_dir: Path, limit: int) -> None:
    if limit <= 0:
        return
    done = 0
    for case in cases:
        if done >= limit:
            return
        for rel in case.local_images[:1]:
            if done >= limit:
                return
            text = run_ocr(output_dir / rel)
            done += 1
            if not text:
                continue
            lowered = text.lower()
            if any(word in lowered for word in ["watermark", "pollo", "logo", "ai"]):
                case.watermark_signals.append("ocr_text:" + text[:200].replace("\n", " "))
                if case.watermark_status == "needs_review":
                    case.watermark_status = "suspected_from_ocr"


def write_outputs(cases: list[GalleryCase], output_dir: Path, source_pages: dict[str, str]) -> None:
    records_dir = output_dir / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    all_json = records_dir / "evolink_cases.json"
    jsonl = records_dir / "evolink_cases.jsonl"
    csv = records_dir / "evolink_cases.csv"
    source_dir = output_dir / "source_markdown"
    source_dir.mkdir(parents=True, exist_ok=True)
    for name, text in source_pages.items():
        (source_dir / name).write_text(text, encoding="utf-8")

    rows = [case.__dict__ for case in cases]
    all_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with jsonl.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with csv.open("w", encoding="utf-8") as handle:
        headers = [
            "id",
            "case_no",
            "title",
            "category",
            "source_url",
            "source_author",
            "image_count",
            "local_images",
            "watermark_status",
            "watermark_signals",
            "tags",
            "prompt",
        ]
        handle.write(",".join(headers) + "\n")
        for case in cases:
            values = [
                case.id,
                str(case.case_no),
                case.title,
                case.category,
                case.source_url,
                case.source_author or "",
                str(len(case.local_images)),
                "|".join(case.local_images),
                case.watermark_status,
                "|".join(case.watermark_signals),
                "|".join(case.tags),
                case.prompt.replace("\n", "\\n"),
            ]
            handle.write(",".join(csv_escape(value) for value in values) + "\n")

    summary = {
        "source_repo": f"https://github.com/{REPO}",
        "license": "CC0-1.0",
        "case_count": len(cases),
        "image_count": sum(len(case.local_images) for case in cases),
        "categories": {
            category: sum(1 for case in cases if case.category == category)
            for category in sorted({case.category for case in cases})
        },
        "watermark_status": {
            status: sum(1 for case in cases if case.watermark_status == status)
            for status in sorted({case.watermark_status for case in cases})
        },
        "notes": [
            "Images/prompts are from the CC0 repository metadata, but brand/person/trademark rights still need review.",
            "watermark_status is an automated first pass and should be reviewed before publishing.",
        ],
    }
    (output_dir / "SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def csv_escape(value: str) -> str:
    value = value.replace('"', '""')
    return f'"{value}"'


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect CC0 image prompt gallery seed data.")
    parser.add_argument("--output", default="../happyimage-gallery-source/image-gallery-seed", help="Output directory")
    parser.add_argument("--skip-download", action="store_true", help="Only create metadata")
    parser.add_argument("--workers", type=int, default=12, help="Concurrent image downloads")
    parser.add_argument(
        "--ocr-limit",
        type=int,
        default=0,
        help="Optional number of cases to run tesseract OCR against for watermark signals",
    )
    args = parser.parse_args()

    output_dir = Path(args.output).resolve()
    images_dir = output_dir / "images"
    output_dir.mkdir(parents=True, exist_ok=True)

    cases: list[GalleryCase] = []
    source_pages: dict[str, str] = {}
    for category, path in CATEGORY_FILES.items():
        text = fetch_text(f"{RAW_BASE}/{path}")
        source_pages[Path(path).name] = text
        cases.extend(parse_cases(category, text))

    for case in cases:
        case.tags = infer_tags(case)
        case.watermark_status, case.watermark_signals = infer_watermark(case)
        case.local_images = [
            str(Path("images") / filename_for(url, case.id, index))
            for index, url in enumerate(case.image_urls)
        ]

    if not args.skip_download:
        jobs = []
        for case in cases:
            for url, rel in zip(case.image_urls, case.local_images):
                jobs.append((url, output_dir / rel))
        failures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for dest, ok, error in pool.map(download_one, jobs):
                if not ok:
                    failures.append({"path": dest, "error": error})
        if failures:
            (output_dir / "download_failures.json").write_text(
                json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        else:
            (output_dir / "download_failures.json").unlink(missing_ok=True)
        for case in cases:
            add_dimensions(case, output_dir)

    maybe_ocr_cases(cases, output_dir, args.ocr_limit)
    write_outputs(cases, output_dir, source_pages)

    summary = json.loads((output_dir / "SUMMARY.json").read_text(encoding="utf-8"))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
