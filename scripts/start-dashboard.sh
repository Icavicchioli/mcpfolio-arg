#!/bin/bash

# Configuration
PORT=${PORT:-8000}
CONDA_ENV="quant-ollama-analyst"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   Quant-Ollama Dashboard Startup      ${NC}"
echo -e "${BLUE}========================================${NC}"

# 1. Check Ollama
echo -e "${YELLOW}⚙️  Checking Ollama status...${NC}"
if ! ollama list >/dev/null 2>&1; then
    echo -e "${YELLOW}🚀 Starting Ollama serve...${NC}"
    ollama serve >/dev/null 2>&1 &
    sleep 5
else
    echo -e "${GREEN}✅ Ollama is already running.${NC}"
fi

# 2. Start Backend (FastAPI)
echo -e "${YELLOW}🔌 Starting Backend Server...${NC}"
cd "$(dirname "$0")/.."
# Kill existing uvicorn process on this port if any
pkill -f "uvicorn src.web.main:app" >/dev/null 2>&1

conda run -n ${CONDA_ENV} python -m uvicorn src.web.main:app --host 127.0.0.1 --port ${PORT} >/dev/null 2>&1 &
BACKEND_PID=$!

# 3. Wait for Health Check
echo -e "${YELLOW}⏳ Waiting for health check...${NC}"
MAX_RETRIES=30
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -s http://127.0.0.1:${PORT}/api/health | grep -q '"healthy"'; then
        echo -e "${GREEN}✅ Backend is healthy!${NC}"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    sleep 1
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo -e "\033[0;31m❌ Backend failed to start or is unhealthy.${NC}"
    exit 1
fi

# 4. Open Browser
URL="http://127.0.0.1:${PORT}"
echo -e "${GREEN}🌐 Opening Dashboard at ${URL}${NC}"
open "${URL}" || xdg-open "${URL}" || echo -e "Please open ${URL} in your browser."

echo -e "${BLUE}----------------------------------------${NC}"
echo -e "${GREEN}🚀 Platform is ready!${NC}"
echo -e "Press Ctrl+C to stop the servers."
echo -e "${BLUE}----------------------------------------${NC}"

# Keep script running to allow stopping with Ctrl+C
wait $BACKEND_PID
