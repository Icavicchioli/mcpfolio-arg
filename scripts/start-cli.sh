#!/usr/bin/env bash
# Start the MCPFolio CLI in interactive mode
#
# Usage: ./scripts/start-cli.sh

set -e

# Colors
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  MCPFolio CLI${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# Check if conda environment is activated
if [[ -z "${CONDA_DEFAULT_ENV}" ]] || [[ "${CONDA_DEFAULT_ENV}" != "mcpfolio" ]]; then
    echo "Activating conda environment: mcpfolio"
    source ~/miniconda3/etc/profile.d/conda.sh
    conda activate mcpfolio
fi

# Start CLI
cd "$(dirname "$0")/.."
python -m src.cli interactive
