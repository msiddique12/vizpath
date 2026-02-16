#!/bin/bash
# Vizpath Demo Startup Script
# Starts all services in a single terminal for easy demos

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${GREEN}Starting Vizpath...${NC}"
echo ""

# Detect docker compose command
if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
elif docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
else
    echo -e "${YELLOW}Error: docker compose is not installed.${NC}"
    exit 1
fi

# Check for NVIDIA_API_KEY
if [ -z "${NVIDIA_API_KEY:-}" ]; then
    echo -e "${YELLOW}Warning: NVIDIA_API_KEY not set. Intelligence features will not work.${NC}"
    echo "Set it with: export NVIDIA_API_KEY='nvapi-...'"
    echo ""
fi

# Start docker services (postgres + redis)
echo -e "${BLUE}[1/3]${NC} Starting database services..."
"${COMPOSE_CMD[@]}" up -d postgres redis
sleep 3

# Wait for postgres to be ready
echo -e "${BLUE}[2/3]${NC} Waiting for database..."
DB_READY=false
for i in {1..30}; do
    if "${COMPOSE_CMD[@]}" exec -T postgres pg_isready -U vizpath > /dev/null 2>&1; then
        DB_READY=true
        break
    fi
    sleep 1
done

if [ "$DB_READY" = false ]; then
    echo -e "${YELLOW}Error: Postgres did not become ready in time.${NC}"
    exit 1
fi

# Start server in background
echo -e "${BLUE}[3/3]${NC} Starting services..."
cd "$SCRIPT_DIR/server"
DATABASE_URL=postgresql://vizpath:vizpath@localhost:5432/vizpath \
REDIS_URL=redis://localhost:6379 \
uvicorn app.main:app --reload --port 8000 &
SERVER_PID=$!
cd "$SCRIPT_DIR"

# Start dashboard in background
cd "$SCRIPT_DIR/dashboard"
npm run dev &
DASH_PID=$!
cd "$SCRIPT_DIR"

# Wait a moment for services to start
sleep 3

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Vizpath is running!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  ${BLUE}Dashboard:${NC}  http://localhost:3000"
echo -e "  ${BLUE}API:${NC}        http://localhost:8000"
echo -e "  ${BLUE}API Docs:${NC}   http://localhost:8000/docs"
echo ""
echo -e "${YELLOW}Run the demo agent:${NC}"
echo "  python -m examples.code_agent.run 'How does the intelligence module work?'"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

# Cleanup function
cleanup() {
    echo ""
    echo -e "${BLUE}Stopping services...${NC}"
    if [ -n "${SERVER_PID:-}" ]; then
        kill "$SERVER_PID" 2>/dev/null || true
    fi
    if [ -n "${DASH_PID:-}" ]; then
        kill "$DASH_PID" 2>/dev/null || true
    fi
    "${COMPOSE_CMD[@]}" down
    echo -e "${GREEN}Vizpath stopped.${NC}"
    exit 0
}

# Set up trap for cleanup
trap cleanup EXIT INT TERM

# Wait for background processes
wait
