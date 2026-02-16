#!/usr/bin/env bash
# Quick check script for rapid iteration
# Runs faster subset of checks
#
# Usage: ./scripts/quick-check.sh

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}>>> Quick Check${NC}"

# Check if conda environment is activated
if [[ -z "${CONDA_DEFAULT_ENV}" ]] || [[ "${CONDA_DEFAULT_ENV}" != "mcpfolio" ]]; then
    source ~/miniconda3/etc/profile.d/conda.sh
    conda activate mcpfolio
fi

# Run formatters
echo -e "\n${YELLOW}Formatting code...${NC}"
black src/ tests/
isort src/ tests/

# Run linter
echo -e "\n${YELLOW}Linting...${NC}"
ruff check --fix --ignore=PTH123 src/ tests/

# Run quick tests (not integration)
echo -e "\n${YELLOW}Running unit tests...${NC}"
pytest tests/unit/ -v --tb=short

echo -e "\n${GREEN}✓ Quick check passed!${NC}\n"
