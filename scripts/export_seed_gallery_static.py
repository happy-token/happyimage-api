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

from services.seed_gallery_service import CANDIDATE_GALLERY_DIR, SEED_GALLERY_INDEX, SeedGalleryService, seed_gallery_service


def _rewrite_image_urls(service: SeedGalleryService, item: dict[str, Any]) -> dict[str, Any]:
    cloned = dict(item)
    images = []
    for image in item.get("images") or []:
        if not isinstance(image, dict):
            continue
        image_copy = dict(image)
        relative = str(image_copy.get("path") or "").removeprefix("images/").lstrip("/")
        if relative:
            image_copy["url"] = f"/seed-gallery/images/{relative}"
            thumbnail_path = service.get_thumbnail_path(640, relative)
            if thumbnail_path and thumbnail_path.is_file():
                image_copy["thumbnail_url"] = f"/seed-gallery/thumbnails/w640/{Path(relative).with_suffix('.webp').as_posix()}"
            else:
                image_copy.pop("thumbnail_url", None)
        images.append(image_copy)
    cloned["images"] = images
    return cloned


def _copy_item_assets(service: SeedGalleryService, items: list[dict[str, Any]], output_dir: Path) -> None:
    copied: set[Path] = set()
    for item in items:
        for image in item.get("images") or []:
            if not isinstance(image, dict):
                continue
            relative = str(image.get("path") or "").removeprefix("images/").lstrip("/")
            if not relative:
                continue
            source_path = service.resolve_image_path(relative)
            if source_path and source_path.is_file():
                target_path = output_dir / "images" / relative
                if target_path not in copied:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_path, target_path)
                    copied.add(target_path)

            thumbnail_path = service.get_thumbnail_path(640, relative)
            if thumbnail_path and thumbnail_path.is_file():
                target_path = output_dir / "thumbnails" / "w640" / Path(relative).with_suffix(".webp")
                if target_path not in copied:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(thumbnail_path, target_path)
                    copied.add(target_path)


def export_static_gallery(service: SeedGalleryService, output_dir: Path, *, copy_assets: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    static_dir = output_dir / "static"
    static_dir.mkdir(parents=True, exist_ok=True)

    items = sorted(service._load_items(), key=service._display_item_priority)  # noqa: SLF001
    public_items = [_rewrite_image_urls(service, item) for item in items]
    facets = service.facets()
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
        _copy_item_assets(service, items, output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the normalized official gallery as a static web asset package.")
    parser.add_argument(
        "--output",
        default="../happytoken-web/public/seed-gallery",
        help="Output directory, usually happytoken-web/public/seed-gallery",
    )
    parser.add_argument(
        "--copy-assets",
        action="store_true",
        help="Copy images and pregenerated thumbnails into the output directory. Omit this when assets are mounted separately.",
    )
    parser.add_argument(
        "--seed-dir",
        default="",
        help="Optional seed gallery directory containing records/evolink_cases.json and images/.",
    )
    parser.add_argument(
        "--candidate-dir",
        default="",
        help="Optional candidate gallery root containing */records/candidates.json and */images/.",
    )
    args = parser.parse_args()
    if args.seed_dir or args.candidate_dir:
        seed_dir = Path(args.seed_dir).expanduser().resolve() if args.seed_dir else SEED_GALLERY_INDEX.parents[1]
        service = SeedGalleryService(
            index_file=seed_dir / "records" / "evolink_cases.json",
            images_dir=seed_dir / "images",
            candidate_root=Path(args.candidate_dir).expanduser().resolve() if args.candidate_dir else CANDIDATE_GALLERY_DIR,
        )
    else:
        service = seed_gallery_service
    export_static_gallery(service, Path(args.output).resolve(), copy_assets=args.copy_assets)


if __name__ == "__main__":
    main()
