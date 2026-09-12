#!/usr/bin/env bash
# ==============================================================================
# AWGP Audiobook Production Pipeline - Unified Startup Script
# Starts both the FastAPI Backend (:8000) and the Vite Frontend (:5173).
# Gracefully terminates all child processes on Ctrl+C.
# ==============================================================================

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Terminal Colors
BLUE='\033[1;34m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RED='\033[1;31m'
NC='\033[0m'

echo -e "${BLUE}======================================================${NC}"
echo -e "${GREEN}    AWGP Audiobook Production Pipeline Launcher       ${NC}"
echo -e "${BLUE}======================================================${NC}"

# Clean any existing orphaned processes on ports 8000 and 5173
echo -e "${YELLOW}[1/4] Checking and freeing ports 8000 and 5173...${NC}"
fuser -k 8000/tcp 2>/dev/null || true
fuser -k 5173/tcp 2>/dev/null || true

# Activate Python Virtual Environment
echo -e "${YELLOW}[2/4] Activating Python virtual environment...${NC}"
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d "../venv" ]; then
    source ../venv/bin/activate
else
    echo -e "${RED}Error: Virtual environment (venv) not found! Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt${NC}"
    exit 1
fi

# Export environment variables from .env if present
if [ -f ".env" ]; then
    echo -e "${YELLOW}      Loading environment variables from .env...${NC}"
    export $(grep -v '^#' .env | xargs)
fi

# Track PID array for cleanup
PIDS=()

cleanup() {
    echo ""
    echo -e "${YELLOW}Stopping all services gracefully...${NC}"
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    wait 2>/dev/null || true
    # Final port safety sweep
    fuser -k 8000/tcp 2>/dev/null || true
    fuser -k 5173/tcp 2>/dev/null || true
    echo -e "${GREEN}All services stopped cleanly. Goodbye!${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# Start FastAPI Backend
echo -e "${YELLOW}[3/4] Starting FastAPI Backend on http://localhost:8000...${NC}"
uvicorn api:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
PIDS+=($BACKEND_PID)

# Wait briefly for backend to initialize
sleep 2

# Start Vite Frontend
echo -e "${YELLOW}[4/4] Starting Vite Frontend on http://localhost:5173...${NC}"
cd "$PROJECT_ROOT/frontend"
npm run dev -- --host 0.0.0.0 &
FRONTEND_PID=$!
PIDS+=($FRONTEND_PID)

echo ""
echo -e "${GREEN}======================================================${NC}"
echo -e "${GREEN}  ✓ Backend running at:  http://localhost:8000       ${NC}"
echo -e "${GREEN}  ✓ API Docs running at: http://localhost:8000/docs  ${NC}"
echo -e "${GREEN}  ✓ Frontend running at: http://localhost:5173       ${NC}"
echo -e "${GREEN}======================================================${NC}"
echo -e "${YELLOW}Press [Ctrl+C] at any time to stop both servers.${NC}"
echo ""

# Wait for background processes
wait
