#!/bin/bash
# Vizpath Demo Startup Script
# One command to install dependencies and start all services

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

# Detect Python binary
if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    echo -e "${YELLOW}Error: Python is not installed.${NC}"
    exit 1
fi

# Verify npm is installed
if ! command -v npm >/dev/null 2>&1; then
    echo -e "${YELLOW}Error: npm is not installed. Please install Node.js 20+.${NC}"
    exit 1
fi

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

# ============================================
# Auto-install dependencies if needed
# ============================================

# Check and install SDK
if ! "$PYTHON_BIN" -c "import vizpath" 2>/dev/null; then
    echo -e "${BLUE}[Setup]${NC} Installing SDK..."
    "$PYTHON_BIN" -m pip install -q -e "$SCRIPT_DIR/sdk"
fi

# Check and install server dependencies (includes uvicorn)
if ! "$PYTHON_BIN" -c "import uvicorn; import fastapi" 2>/dev/null; then
    echo -e "${BLUE}[Setup]${NC} Installing server dependencies..."
    "$PYTHON_BIN" -m pip install -q -e "$SCRIPT_DIR/server[dev]"
fi

# Check and install dashboard dependencies
if [ ! -d "$SCRIPT_DIR/dashboard/node_modules" ]; then
    echo -e "${BLUE}[Setup]${NC} Installing dashboard dependencies..."
    (cd "$SCRIPT_DIR/dashboard" && npm install --silent)
fi

# ============================================
# Start services
# ============================================

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
NVIDIA_LLM_MODEL=nvidia/nemotron-4-340b-instruct \
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
