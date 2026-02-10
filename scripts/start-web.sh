#!/usr/bin/env bash
# Start the Quant-Ollama web interface
#
# Usage: ./scripts/start-web.sh [port]

set -e

PORT="${1:-8000}"

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  Quant-Ollama Web Interface${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# Check if conda environment is activated
if [[ -z "${CONDA_DEFAULT_ENV}" ]] || [[ "${CONDA_DEFAULT_ENV}" != "quant-ollama-analyst" ]]; then
    echo "Activating conda environment: quant-ollama-analyst"
    source ~/miniconda3/etc/profile.d/conda.sh
    conda activate quant-ollama-analyst
fi

echo -e "${GREEN}→${NC} Starting web server on port ${PORT}..."
echo -e "${GREEN}→${NC} Open your browser to: http://localhost:${PORT}"
echo -e "${GREEN}→${NC} API documentation: http://localhost:${PORT}/docs"
echo -e "${GREEN}→${NC} Press Ctrl+C to stop"
echo ""

# Start uvicorn
cd "$(dirname "$0")/.."
python -m uvicorn src.web.main:app --host 127.0.0.1 --port "${PORT}" --reload
