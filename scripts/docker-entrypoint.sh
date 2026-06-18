#!/usr/bin/env sh
set -eu

DATA_DIR="${HAPPYIMAGE_DATA_DIR:-/app/data}"
SEED_DIR="/app/seed-data/image-gallery-seed"
TARGET_SEED_DIR="$DATA_DIR/image-gallery-seed"
THUMBNAIL_WIDTHS="${HAPPYIMAGE_THUMBNAIL_WIDTHS:-640}"

mkdir -p "$DATA_DIR"

if [ -d "$SEED_DIR" ] && [ ! -f "$TARGET_SEED_DIR/records/evolink_cases.json" ]; then
  echo "Initializing seed gallery data in $TARGET_SEED_DIR"
  mkdir -p "$TARGET_SEED_DIR"
  cp -a "$SEED_DIR/." "$TARGET_SEED_DIR/"
fi

case "${HAPPYIMAGE_PREGENERATE_THUMBNAILS_ON_START:-false}" in
  1|true|TRUE|yes|YES|on|ON)
    echo "Pregenerating seed gallery thumbnails at widths: $THUMBNAIL_WIDTHS"
    uv run python scripts/pregenerate_seed_gallery_thumbnails.py --widths "$THUMBNAIL_WIDTHS" --quiet
    ;;
esac

exec "$@"
