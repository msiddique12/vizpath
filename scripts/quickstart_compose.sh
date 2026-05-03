#!/usr/bin/env bash
# Zero-install local quickstart: starts full stack and seeds story-mode traces.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v curl >/dev/null 2>&1; then
  echo "Error: curl is required."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required."
  exit 1
fi

if command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
elif docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
else
  echo "Error: docker compose is required."
  exit 1
fi

echo "[1/4] Starting Docker services (postgres, redis, server, dashboard)..."
"${COMPOSE_CMD[@]}" up -d --build

wait_for_url() {
  local url="$1"
  local label="$2"
  local attempts="${3:-90}"
  local sleep_seconds="${4:-1}"

  for _ in $(seq 1 "$attempts"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$sleep_seconds"
  done

  echo "Error: ${label} did not become healthy in time (${url})."
  return 1
}

echo "[2/4] Waiting for API and dashboard health..."
wait_for_url "http://127.0.0.1:8000/health" "API"
wait_for_url "http://127.0.0.1:3000/" "Dashboard"

echo "[3/4] Creating demo project API key..."
PROJECT_NAME="demo-$(date +%Y%m%d-%H%M%S)"
PROJECT_JSON="$(curl -fsS -X POST "http://127.0.0.1:8000/api/v1/projects/" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"${PROJECT_NAME}\"}")"
API_KEY="$(printf '%s' "$PROJECT_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"])')"

echo "[4/4] Seeding story mode traces..."
SEED_JSON="$(curl -fsS -X POST "http://127.0.0.1:8000/api/v1/demo/story-mode" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{"scenario":"agent_regression"}')"

TRACE_IDS="$(printf '%s' "$SEED_JSON" | python3 -c 'import json,sys; print(", ".join(json.load(sys.stdin).get("trace_ids", [])))')"

echo ""
echo "Quickstart complete."
echo "Dashboard:  http://localhost:3000"
echo "API:        http://localhost:8000"
echo "API docs:   http://localhost:8000/docs"
echo ""
echo "Demo API key (project ${PROJECT_NAME}):"
echo "  ${API_KEY}"
echo ""
echo "Seeded traces:"
echo "  ${TRACE_IDS}"
echo ""
echo "Stop services with:"
echo "  ${COMPOSE_CMD[*]} down"
