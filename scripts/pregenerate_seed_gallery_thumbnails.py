from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.seed_gallery_service import CANDIDATE_GALLERY_DIR, SEED_GALLERY_INDEX, THUMBNAIL_WIDTHS, SeedGalleryService, seed_gallery_service


def parse_widths(value: str) -> list[int]:
    widths: list[int] = []
    for raw_width in value.split(","):
        raw_width = raw_width.strip()
        if not raw_width:
            continue
        try:
            width = int(raw_width)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid thumbnail width: {raw_width}") from exc
        if width not in THUMBNAIL_WIDTHS:
            allowed = ", ".join(str(item) for item in sorted(THUMBNAIL_WIDTHS))
            raise argparse.ArgumentTypeError(f"unsupported width {width}; allowed: {allowed}")
        widths.append(width)
    if not widths:
        raise argparse.ArgumentTypeError("at least one width is required")
    return sorted(set(widths))


def is_current_thumbnail(path: Path | None, source_path: Path | None) -> bool:
    if path is None or source_path is None:
        return False
    return path.is_file() and path.suffix == ".webp" and path.stat().st_mtime >= source_path.stat().st_mtime


def main() -> int:
    parser = argparse.ArgumentParser(description="Pregenerate seed gallery WebP thumbnails.")
    parser.add_argument(
        "--widths",
        type=parse_widths,
        default=[640],
        help="Comma-separated thumbnail widths to generate. Allowed: 320,640,960. Default: 640.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N images. Default: all.")
    parser.add_argument("--quiet", action="store_true", help="Only print the final summary.")
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

    service = seed_gallery_service
    if args.seed_dir or args.candidate_dir:
        seed_dir = Path(args.seed_dir).expanduser().resolve() if args.seed_dir else SEED_GALLERY_INDEX.parents[1]
        service = SeedGalleryService(
            index_file=seed_dir / "records" / "evolink_cases.json",
            images_dir=seed_dir / "images",
            candidate_root=Path(args.candidate_dir).expanduser().resolve() if args.candidate_dir else CANDIDATE_GALLERY_DIR,
        )

    image_paths = service.list_image_paths()
    if args.limit > 0:
        image_paths = image_paths[: args.limit]

    total_jobs = len(image_paths) * len(args.widths)
    created = 0
    skipped = 0
    unsupported: list[str] = []
    failed: list[str] = []

    if not args.quiet:
        print(
            f"Pregenerating {total_jobs} thumbnails for {len(image_paths)} images at widths {args.widths}.",
            flush=True,
        )

    job_index = 0
    for image_path in image_paths:
        source_path = service.resolve_image_path(image_path)
        for width in args.widths:
            job_index += 1
            thumbnail_path = service.get_thumbnail_path(width, image_path)
            was_current = is_current_thumbnail(thumbnail_path, source_path)
            resolved = service.resolve_thumbnail_path(width, image_path)
            if resolved is None or resolved.suffix != ".webp":
                if resolved == source_path:
                    unsupported.append(f"{width}:{image_path}")
                else:
                    failed.append(f"{width}:{image_path}")
            elif was_current:
                skipped += 1
            elif is_current_thumbnail(resolved, source_path):
                created += 1
            else:
                failed.append(f"{width}:{image_path}")

            if not args.quiet and (job_index == total_jobs or job_index % 100 == 0):
                print(f"Processed {job_index}/{total_jobs} thumbnails...", flush=True)

    if not args.quiet:
        print()
    print(
        "Thumbnail pregeneration complete: "
        f"{created} created, {skipped} current, {len(unsupported)} unsupported, "
        f"{len(failed)} failed, {total_jobs} total."
    )
    if unsupported:
        print("Unsupported source files:")
        for item in unsupported[:50]:
            print(f"- {item}")
        if len(unsupported) > 50:
            print(f"...and {len(unsupported) - 50} more")
    if failed:
        print("Failed thumbnails:")
        for item in failed[:50]:
            print(f"- {item}")
        if len(failed) > 50:
            print(f"...and {len(failed) - 50} more")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
