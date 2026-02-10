#!/usr/bin/env bash
# Start the Quant-Ollama CLI in interactive mode
#
# Usage: ./scripts/start-cli.sh

set -e

# Colors
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  Quant-Ollama CLI${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# Check if conda environment is activated
if [[ -z "${CONDA_DEFAULT_ENV}" ]] || [[ "${CONDA_DEFAULT_ENV}" != "quant-ollama-analyst" ]]; then
    echo "Activating conda environment: quant-ollama-analyst"
    source ~/miniconda3/etc/profile.d/conda.sh
    conda activate quant-ollama-analyst
fi

# Start CLI
cd "$(dirname "$0")/.."
python -m src.cli interactive
