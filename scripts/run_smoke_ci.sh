#!/usr/bin/env bash
# Run a deterministic smoke E2E stack for CI.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SERVER_LOG="$(mktemp -t vizpath-server-smoke.XXXXXX.log)"
DASHBOARD_LOG="$(mktemp -t vizpath-dashboard-smoke.XXXXXX.log)"
SERVER_PID=""
DASHBOARD_PID=""

cleanup() {
  local exit_code=$?
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "$DASHBOARD_PID" ]]; then
    kill "$DASHBOARD_PID" >/dev/null 2>&1 || true
  fi
  docker compose down -v >/dev/null 2>&1 || true

  if [[ $exit_code -ne 0 ]]; then
    echo "===== server log ====="
    cat "$SERVER_LOG" || true
    echo "===== dashboard log ====="
    cat "$DASHBOARD_LOG" || true
    echo "===== docker compose logs ====="
    docker compose logs postgres redis || true
  fi

  rm -f "$SERVER_LOG" "$DASHBOARD_LOG"
  exit "$exit_code"
}
trap cleanup EXIT

docker compose up -d postgres redis

(
  cd server
  DATABASE_URL="postgresql://vizpath:vizpath@127.0.0.1:5432/vizpath" \
  REDIS_URL="redis://127.0.0.1:6379" \
  uvicorn app.main:app --host 127.0.0.1 --port 8000
) >"$SERVER_LOG" 2>&1 &
SERVER_PID="$!"

npm --prefix dashboard run build >/dev/null
npm --prefix dashboard run preview -- --host 127.0.0.1 --port 4173 >"$DASHBOARD_LOG" 2>&1 &
DASHBOARD_PID="$!"

python scripts/smoke_e2e.py
