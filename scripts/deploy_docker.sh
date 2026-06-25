#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${HAPPYTOKEN_DEPLOY_HOST:?Set HAPPYTOKEN_DEPLOY_HOST to your deploy target}"
REMOTE_COMPOSE_DIR="${HAPPYTOKEN_DEPLOY_COMPOSE_DIR:?Set HAPPYTOKEN_DEPLOY_COMPOSE_DIR to your remote compose directory}"
SERVICE="${HAPPYTOKEN_DEPLOY_SERVICE:-happytoken}"
HEALTH_URL="${HAPPYTOKEN_DEPLOY_HEALTH_URL:-http://localhost:3000/health?format=json}"

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
