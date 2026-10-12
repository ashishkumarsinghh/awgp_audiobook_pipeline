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

# Portable function to free ports (supports fuser on Linux, lsof on macOS/BSD/Git Bash)
free_port() {
    local port=$1
    if command -v fuser >/dev/null 2>&1; then
        fuser -k "${port}/tcp" 2>/dev/null || true
    elif command -v lsof >/dev/null 2>&1; then
        lsof -ti:"${port}" | xargs kill -9 2>/dev/null || true
    fi
}

# Clean any existing orphaned processes on ports 8000 and 5173
echo -e "${YELLOW}[1/4] Checking and freeing ports 8000 and 5173...${NC}"
free_port 8000
free_port 5173

# Activate Python Virtual Environment (supports Linux/macOS bin/ and Windows/Git Bash Scripts/)
echo -e "${YELLOW}[2/4] Activating Python virtual environment...${NC}"
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
elif [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f ".venv/Scripts/activate" ]; then
    source .venv/Scripts/activate
elif [ -f "../venv/bin/activate" ]; then
    source ../venv/bin/activate
elif [ -f "../venv/Scripts/activate" ]; then
    source ../venv/Scripts/activate
elif command -v uvicorn >/dev/null 2>&1; then
    echo -e "${YELLOW}      Using system/active Python environment...${NC}"
else
    echo -e "${RED}Error: Virtual environment (venv) not found and uvicorn is not in PATH!${NC}"
    echo -e "${YELLOW}Run: python3 -m venv venv && pip install -r requirements.txt${NC}"
    exit 1
fi

# Export environment variables from .env if present
if [ -f ".env" ]; then
    echo -e "${YELLOW}      Loading environment variables from .env...${NC}"
    set -a
    . ./.env 2>/dev/null || true
    set +a
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
    free_port 8000
    free_port 5173
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
