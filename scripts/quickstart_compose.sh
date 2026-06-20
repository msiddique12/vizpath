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

if [ ! -f "$ROOT_DIR/.env" ]; then
  if [ -f "$ROOT_DIR/.env.example" ]; then
    echo "[setup] Creating .env from .env.example"
    cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
  else
    echo "Error: .env.example is missing."
    exit 1
  fi
fi

eval "$(python3 "$ROOT_DIR/scripts/export_env.py" --env "$ROOT_DIR/.env" --preserve-existing)"

export POSTGRES_HOST_PORT="${POSTGRES_HOST_PORT:-5433}"
export REDIS_HOST_PORT="${REDIS_HOST_PORT:-6380}"
export NVIDIA_BASE_URL="${NVIDIA_BASE_URL:-https://integrate.api.nvidia.com/v1}"
export NVIDIA_LLM_MODEL="${NVIDIA_LLM_MODEL:-nvidia/llama-3.3-nemotron-super-49b-v1.5}"

if [[ "${NVIDIA_API_KEY:-}" == "your_nvidia_api_key_here" || "${NVIDIA_API_KEY:-}" == "nvidia_api_key_here" ]]; then
  echo "Warning: NVIDIA_API_KEY is still a placeholder in .env; AI features will be disabled."
  export NVIDIA_API_KEY=""
fi

echo "[setup] Validating .env"
python3 "$ROOT_DIR/scripts/check_env.py" --env "$ROOT_DIR/.env"

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

echo "[3/5] Running demo preflight checks..."
PREFLIGHT_JSON="$(curl -fsS "http://127.0.0.1:8000/api/v1/demo/preflight")"
CAN_SEED="$(
  printf '%s' "$PREFLIGHT_JSON" \
    | python3 -c 'import json,sys; print("true" if json.load(sys.stdin).get("can_seed") else "false")'
)"

if [[ "$CAN_SEED" != "true" ]]; then
  echo "Error: demo preflight failed. Cannot seed demo traces."
  printf '%s' "$PREFLIGHT_JSON" | python3 -c '
import json,sys
p=json.load(sys.stdin)
blockers=p.get("blockers", [])
fixes=p.get("fix_commands", [])
if blockers:
    print("Blockers:")
    for b in blockers:
        print(f"  - {b}")
if fixes:
    print("Suggested fixes:")
    for f in fixes:
        print(f"  - {f}")
'
  exit 1
fi

printf '%s' "$PREFLIGHT_JSON" | python3 -c '
import json,sys
p=json.load(sys.stdin)
checks=p.get("checks", [])
warnings=[c for c in checks if c.get("status")=="warning"]
if warnings:
    print("Preflight warnings:")
    for w in warnings:
        comp=w.get("component","unknown")
        msg=w.get("message","")
        print(f"  - [{comp}] {msg}")
'

echo "[4/5] Creating demo project API key..."
PROJECT_NAME="demo-$(date +%Y%m%d-%H%M%S)"
PROJECT_JSON="$(curl -fsS -X POST "http://127.0.0.1:8000/api/v1/projects/" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"${PROJECT_NAME}\"}")"
API_KEY="$(printf '%s' "$PROJECT_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"])')"

echo "[5/5] Seeding story mode traces..."
SEED_JSON="$(curl -fsS -X POST "http://127.0.0.1:8000/api/v1/demo/story-mode" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{"scenario":"agent_regression"}')"

TRACE_IDS="$(printf '%s' "$SEED_JSON" | python3 -c 'import json,sys; print(", ".join(json.load(sys.stdin).get("trace_ids", [])))')"
STORY_MODE_FOUND="$(
  curl -fsS "http://127.0.0.1:8000/api/v1/demo/story-mode/latest" -H "X-API-Key: ${API_KEY}" \
    | python3 -c 'import json,sys; print("true" if json.load(sys.stdin).get("found") else "false")'
)"
if [[ "$STORY_MODE_FOUND" != "true" ]]; then
  echo "Error: story mode seed verification failed."
  exit 1
fi

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
