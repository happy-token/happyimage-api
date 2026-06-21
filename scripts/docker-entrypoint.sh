#!/usr/bin/env sh
set -eu

DATA_DIR="${HAPPYIMAGE_DATA_DIR:-/app/data}"

mkdir -p "$DATA_DIR"

exec "$@"
