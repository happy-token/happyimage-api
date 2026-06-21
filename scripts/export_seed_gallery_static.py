from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.seed_gallery_service import seed_gallery_service


def _rewrite_image_urls(item: dict[str, Any]) -> dict[str, Any]:
    cloned = dict(item)
    images = []
    for image in item.get("images") or []:
        if not isinstance(image, dict):
            continue
        image_copy = dict(image)
        relative = str(image_copy.get("path") or "").removeprefix("images/").lstrip("/")
        if relative:
            image_copy["url"] = f"/seed-gallery/images/{relative}"
            thumbnail_path = seed_gallery_service.get_thumbnail_path(640, relative)
            if thumbnail_path and thumbnail_path.is_file():
                image_copy["thumbnail_url"] = f"/seed-gallery/thumbnails/w640/{Path(relative).with_suffix('.webp').as_posix()}"
            else:
                image_copy.pop("thumbnail_url", None)
        images.append(image_copy)
    cloned["images"] = images
    return cloned


def _copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.mkdir(parents=True, exist_ok=True)
    for source_path in source.rglob("*"):
        if not source_path.is_file():
            continue
        relative = source_path.relative_to(source)
        target_path = target / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)


def export_static_gallery(output_dir: Path, *, copy_assets: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    static_dir = output_dir / "static"
    static_dir.mkdir(parents=True, exist_ok=True)

    items = sorted(seed_gallery_service._load_items(), key=seed_gallery_service._display_item_priority)  # noqa: SLF001
    public_items = [_rewrite_image_urls(item) for item in items]
    facets = seed_gallery_service.facets()
    generated_at = datetime.now(UTC).isoformat()

    (static_dir / "items.json").write_text(
        json.dumps({"generated_at": generated_at, "total": len(public_items), "items": public_items}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    (static_dir / "facets.json").write_text(
        json.dumps({"generated_at": generated_at, **facets}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (static_dir / "ids.json").write_text(
        json.dumps({"generated_at": generated_at, "ids": [item["id"] for item in public_items]}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    if copy_assets:
        seed_root = seed_gallery_service.images_dir.parent
        _copy_tree(seed_root / "images", output_dir / "images")
        _copy_tree(seed_root / "thumbnails", output_dir / "thumbnails")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the normalized official gallery as a static web asset package.")
    parser.add_argument(
        "--output",
        default="../happyimage-web/public/seed-gallery",
        help="Output directory, usually happyimage-web/public/seed-gallery",
    )
    parser.add_argument(
        "--copy-assets",
        action="store_true",
        help="Copy images and pregenerated thumbnails into the output directory. Omit this when assets are mounted separately.",
    )
    args = parser.parse_args()
    export_static_gallery(Path(args.output).resolve(), copy_assets=args.copy_assets)


if __name__ == "__main__":
    main()
