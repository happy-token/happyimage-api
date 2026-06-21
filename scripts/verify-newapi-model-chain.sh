#!/usr/bin/env bash
set -euo pipefail

WEB_URL="${WEB_URL:-http://127.0.0.1:3000}"
API_URL="${API_URL:-http://127.0.0.1:8000}"
HAPPYIMAGE_AUTH_KEY="${HAPPYIMAGE_AUTH_KEY:-}"

command -v curl >/dev/null || { echo "curl is required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }

if [[ -z "$HAPPYIMAGE_AUTH_KEY" ]]; then
  if [[ -f config.json ]]; then
    HAPPYIMAGE_AUTH_KEY="$(jq -r '."auth-key" // empty' config.json)"
  fi
fi

if [[ -z "$HAPPYIMAGE_AUTH_KEY" ]]; then
  echo "HAPPYIMAGE_AUTH_KEY is required or config.json must contain auth-key" >&2
  exit 1
fi

echo "Checking web /v1/models via NewAPI middleware..."
models="$(curl -fsS "$WEB_URL/v1/models" -H "Authorization: Bearer browser-token")"
echo "$models" | jq -e '.object == "list" and (.data | length > 0)' >/dev/null

echo "Checking API settings redacts model gateway key..."
settings="$(curl -fsS "$API_URL/api/settings" -H "Authorization: Bearer $HAPPYIMAGE_AUTH_KEY")"
echo "$settings" | jq -e '.config | has("model_gateway_api_key") | not' >/dev/null

echo "Checking task API creates a restorable task..."
task_id="verify-$(date +%s)"
task="$(curl -fsS "$API_URL/api/image-tasks/generations" \
  -H "Authorization: Bearer $HAPPYIMAGE_AUTH_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"client_task_id\":\"$task_id\",\"prompt\":\"a clean product photo\",\"model\":\"gpt-image-2\",\"quality\":\"auto\"}")"
echo "$task" | jq -e --arg id "$task_id" '.id == $id and (.status == "queued" or .status == "running" or .status == "success" or .status == "error")' >/dev/null

terminal_task=""
terminal_status=""

for _ in $(seq 1 30); do
  restored="$(curl -fsS "$API_URL/api/image-tasks?ids=$task_id" -H "Authorization: Bearer $HAPPYIMAGE_AUTH_KEY")"
  item="$(echo "$restored" | jq -c '.items[0] // .[0] // empty')"

  if [[ -n "$item" ]]; then
    echo "$item" | jq -e --arg id "$task_id" '.id == $id' >/dev/null
    status="$(echo "$item" | jq -r '.status // empty')"

    if [[ "$status" == "success" || "$status" == "error" ]]; then
      terminal_task="$item"
      terminal_status="$status"
      break
    fi
  fi

  sleep 2
done

if [[ -z "$terminal_task" ]]; then
  echo "Timed out waiting for task $task_id to reach success or error" >&2
  exit 1
fi

if [[ "$terminal_status" == "success" ]]; then
  echo "$terminal_task" | jq -e '((.data // []) | length) > 0' >/dev/null
else
  echo "$terminal_task" | jq -e '((.error // "") | type == "string") and ((.error // "") | length > 0)' >/dev/null
  echo "Task $task_id is restorable but ended in error."
fi

echo "NewAPI model chain verification passed."
