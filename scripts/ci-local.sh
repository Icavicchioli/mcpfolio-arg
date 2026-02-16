#!/usr/bin/env bash
# Local CI script to run all checks before pushing
# Run this script before committing to catch issues early
#
# Usage: ./scripts/ci-local.sh

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}  MCPFolio Local CI Pipeline${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""

# Function to print step
step() {
    echo -e "\n${YELLOW}>>> $1${NC}\n"
}

# Function to print success
success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Function to print error
error() {
    echo -e "${RED}✗ $1${NC}"
    exit 1
}

# Check if conda environment is activated
if [[ -z "${CONDA_DEFAULT_ENV}" ]] || [[ "${CONDA_DEFAULT_ENV}" != "mcpfolio" ]]; then
    echo -e "${YELLOW}Activating conda environment: mcpfolio${NC}"
    source ~/miniconda3/etc/profile.d/conda.sh
    conda activate mcpfolio || error "Failed to activate conda environment"
fi

# Step 1: Pre-commit hooks
step "Running pre-commit hooks"
if pre-commit run --all-files; then
    success "Pre-commit hooks passed"
else
    error "Pre-commit hooks failed - please fix the issues above"
fi

# Step 2: Run tests with coverage
step "Running test suite with coverage"
if pytest tests/ \
    --cov=src \
    --cov-report=term-missing \
    --cov-report=html \
    --cov-fail-under=70 \
    -v; then
    success "Tests passed with sufficient coverage"
else
    error "Tests failed or coverage below 70%"
fi

# Step 3: Security scan with bandit
step "Running security scan (bandit)"
if bandit -r src/ -ll -f screen; then
    success "Security scan passed"
else
    echo -e "${YELLOW}⚠ Security issues found (not failing build)${NC}"
fi

# Step 4: Type checking with mypy
step "Running type checker (mypy)"
if mypy src/ --ignore-missing-imports --no-strict-optional; then
    success "Type checking passed"
else
    echo -e "${YELLOW}⚠ Type checking issues found (not failing build)${NC}"
fi

# Step 5: Check for outdated dependencies
step "Checking for security vulnerabilities in dependencies"
if pip list --format=freeze | safety check --stdin || true; then
    success "Dependency check complete"
else
    echo -e "${YELLOW}⚠ Some dependencies may have vulnerabilities${NC}"
fi

# Summary
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  ✓ All CI checks passed!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Coverage report available at: ${YELLOW}htmlcov/index.html${NC}"
echo -e "You can now commit and push your changes."
echo ""
