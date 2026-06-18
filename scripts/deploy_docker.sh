#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${HAPPYIMAGE_DEPLOY_HOST:?Set HAPPYIMAGE_DEPLOY_HOST to your deploy target}"
REMOTE_COMPOSE_DIR="${HAPPYIMAGE_DEPLOY_COMPOSE_DIR:?Set HAPPYIMAGE_DEPLOY_COMPOSE_DIR to your remote compose directory}"
SERVICE="${HAPPYIMAGE_DEPLOY_SERVICE:-happyimage}"
HEALTH_URL="${HAPPYIMAGE_DEPLOY_HEALTH_URL:-http://localhost:3000/health?format=json}"

ssh "$REMOTE_HOST" "set -euo pipefail
cd '$REMOTE_COMPOSE_DIR'
docker compose build '$SERVICE'
docker compose up -d '$SERVICE'
docker compose ps '$SERVICE'
"

echo "Waiting for $HEALTH_URL ..."
for attempt in $(seq 1 30); do
  if curl -fsS "$HEALTH_URL" >/dev/null; then
    echo "Deployment healthy: $HEALTH_URL"
    exit 0
  fi
  echo "Health check not ready yet ($attempt/30)."
  sleep 2
done

echo "Deployment health check failed: $HEALTH_URL" >&2
exit 1
